import asyncio
import ipaddress
import socket
import tempfile
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlsplit

import aiohttp
from aiohttp.abc import AbstractResolver
from bs4 import BeautifulSoup
from charset_normalizer import from_bytes
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from .document_formats import (
    DOCUMENT_MIMES,
    FORMATS,
    MAX_DOCUMENT_BYTES,
    MAX_TEXT,
    TEXT_MIMES,
    extraction_notes,
)
from .errors import AppError
from .extraction import extract_file


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchArguments(StrictModel):
    query: str = Field(min_length=1, max_length=500)


class URLArguments(StrictModel):
    url: str = Field(min_length=1, max_length=2048)


class AttachmentArguments(StrictModel):
    attachment_id: str = Field(pattern=r"^[0-9a-f-]{36}$")


class SearchTool(StrictModel):
    name: Literal["search_web"]
    arguments: SearchArguments


class URLTool(StrictModel):
    name: Literal["read_url"]
    arguments: URLArguments


class AttachmentTool(StrictModel):
    name: Literal["read_attachment"]
    arguments: AttachmentArguments


class ToolPlan(StrictModel):
    type: Literal["tool"]
    tool: Annotated[SearchTool | URLTool | AttachmentTool, Field(discriminator="name")]


class FinalPlan(StrictModel):
    type: Literal["final"]


PLAN = TypeAdapter(Annotated[ToolPlan | FinalPlan, Field(discriminator="type")])


def parse_plan(raw: str):
    try:
        return PLAN.validate_json(raw)
    except ValidationError:
        raise AppError("TOOL_PLAN_INVALID", "자료를 읽기 위한 요청 형식을 확인하지 못했습니다.") from None


def public_ip(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            return public_ip(str(ip.ipv4_mapped))
        if ip.sixtofour or ip.teredo:
            return False
    return ip.is_global and not ip.is_multicast


def validate_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError
        if parsed.port not in (None, 80, 443) or len(url) > 2048:
            raise ValueError
        host = parsed.hostname.rstrip(".").lower()
        if host in ("localhost", "localhost.localdomain") or host.endswith((".local", ".internal", ".localhost")):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if not public_ip(host):
                raise ValueError
        return url
    except ValueError:
        raise AppError("URL_BLOCKED", "공개된 HTTP 또는 HTTPS 페이지 주소만 읽을 수 있습니다.") from None


class PublicResolver(AbstractResolver):
    """Pin the verified DNS results to the connection, avoiding a second DNS lookup."""
    async def resolve(self, host, port=0, family=socket.AF_INET):
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, family=family, type=socket.SOCK_STREAM)
        if not infos or any(not public_ip(info[4][0]) for info in infos):
            raise AppError("URL_BLOCKED", "사설 네트워크 주소는 읽을 수 없습니다.")
        return [{"hostname": host, "host": info[4][0], "port": port, "family": info[0],
                 "proto": info[2], "flags": socket.AI_NUMERICHOST} for info in infos]

    async def close(self):
        pass


async def fetch_public(url: str, max_bytes: int = 2 * 1024 * 1024, *, documents: bool = False) -> tuple[str, bytes, str]:
    connector = aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False)
    try:
        async with asyncio.timeout(10), aiohttp.ClientSession(connector=connector,
            timeout=aiohttp.ClientTimeout(total=10), trust_env=False,
            headers={"User-Agent": "Modurouter/0.1 (public document reader)"}) as client:
            for _ in range(5):
                validate_url(url)
                async with client.get(url, allow_redirects=False) as response:
                    connection = response.connection
                    if connection and connection.transport:
                        peer = connection.transport.get_extra_info("peername")
                        if peer and not public_ip(peer[0]):
                            raise AppError("URL_BLOCKED", "사설 네트워크 주소는 읽을 수 없습니다.")
                    if response.status in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        if not location:
                            break
                        url = urljoin(url, location)
                        continue
                    if response.status != 200:
                        raise AppError("PAGE_UNAVAILABLE", "페이지를 읽을 수 없습니다.", 503, True)
                    mime = response.content_type
                    if documents and mime in ("application/octet-stream", "application/zip", "application/x-zip-compressed"):
                        mime = FORMATS.get(Path(unquote(urlsplit(url).path)).suffix.lower(), mime)
                    is_document = documents and mime in DOCUMENT_MIMES
                    if not (mime.startswith("text/") or mime in TEXT_MIMES or mime == "application/xhtml+xml" or is_document):
                        raise AppError("PAGE_UNSUPPORTED", "웹페이지나 지원하는 문서 또는 이미지 주소를 입력해 주세요.")
                    limit = MAX_DOCUMENT_BYTES if is_document else max_bytes
                    if response.content_length and response.content_length > limit:
                        raise AppError("PAGE_TOO_LARGE", "페이지 크기 제한을 초과했습니다.")
                    data = bytearray()
                    async for chunk in response.content.iter_chunked(16384):
                        data.extend(chunk)
                        if len(data) > limit:
                            raise AppError("PAGE_TOO_LARGE", "페이지 크기 제한을 초과했습니다.")
                    return url, bytes(data), mime
    except (TimeoutError, aiohttp.ClientError, OSError):
        raise AppError("PAGE_UNAVAILABLE", "페이지에 연결하지 못했습니다.", 503, True) from None
    raise AppError("PAGE_REDIRECT_LIMIT", "페이지 이동이 너무 많아 읽기를 중단했습니다.")


async def read_url(url: str) -> dict:
    final_url, data, mime = await fetch_public(url, documents=True)
    if mime in DOCUMENT_MIMES:
        with tempfile.TemporaryDirectory(prefix="modurouter-web-document-") as directory:
            path = Path(directory) / "document"
            await asyncio.to_thread(path.write_bytes, data)
            result = await extract_file(path, mime)
        if result.get("error"):
            raise AppError(result["error"], "링크의 문서를 읽지 못했습니다. 파일 상태를 확인하거나 직접 첨부해 주세요.")
        return {"title": unquote(urlsplit(final_url).path.rsplit("/", 1)[-1])[:200] or final_url,
                "url": final_url, "text": result["text"], "scope": "page",
                "format": mime, "truncated": result.get("truncated", False), "limitations": extraction_notes(mime)}
    soup = BeautifulSoup(data, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else final_url
    for node in soup(["script", "style", "nav", "header", "footer", "form", "noscript"]):
        node.decompose()
    if mime in ("text/html", "application/xhtml+xml"):
        body = soup.find("main") or soup.find("article") or soup
        content = body.get_text("\n", strip=True)
    else:
        decoded = from_bytes(data).best()
        content = str(decoded) if decoded is not None else data.decode("utf-8", errors="replace")
    if not content:
        raise AppError("PAGE_EMPTY", "페이지에서 읽을 수 있는 본문을 찾지 못했습니다.")
    return {"title": title[:200], "url": final_url, "text": content[:MAX_TEXT],
            "scope": "page", "truncated": len(content) > MAX_TEXT}


async def search_web(query: str) -> list[dict]:
    for endpoint in ("https://html.duckduckgo.com/html/", "https://lite.duckduckgo.com/lite/"):
        try:
            _, data, _ = await fetch_public(endpoint + "?" + urlencode({"q": query}))
            soup = BeautifulSoup(data, "html.parser")
            result, seen = [], set()
            for link in soup.select(".result__a, .result-link"):
                if not link.get("href"):
                    continue
                row = link.find_parent(class_="result")
                snippet = row.select_one(".result__snippet") if row else None
                url = urljoin("https://duckduckgo.com", link["href"])
                parsed = urlsplit(url)
                if parsed.hostname == "duckduckgo.com" or (parsed.hostname or "").endswith(".duckduckgo.com"):
                    url = parse_qs(parsed.query).get("uddg", [url])[0]
                try:
                    validate_url(url)
                except AppError:
                    continue
                if url in seen:
                    continue
                seen.add(url)
                result.append({"title": link.get_text(" ", strip=True)[:200], "url": url,
                               "text": snippet.get_text(" ", strip=True)[:2000] if snippet else "",
                               "scope": "search_snippet", "truncated": False})
                if len(result) == 5:
                    break
            if result:
                return result
        except AppError:
            continue
    raise AppError("SEARCH_UNAVAILABLE", "웹 검색을 사용할 수 없습니다. 페이지 주소를 직접 입력하거나 검색을 꺼 주세요.", 503, True)
