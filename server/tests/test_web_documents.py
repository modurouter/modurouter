import asyncio
from io import BytesIO

import pytest
from docx import Document
from modurouter import tools
from modurouter.document_formats import DOCX, MAX_DOCUMENT_BYTES
from modurouter.errors import AppError
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def fake_http(monkeypatch, mime, chunks=(), length=None):
    requested = []

    class Response:
        connection = None
        status = 200
        headers = {}
        content_type = mime
        content_length = length

        @property
        def content(self):
            return self

        async def iter_chunked(self, size):
            for chunk in chunks:
                yield chunk

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class Client:
        def __init__(self, **kwargs):
            self.connector = kwargs["connector"]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            await self.connector.close()

        def get(self, url, **kwargs):
            requested.append(url)
            assert kwargs["allow_redirects"] is False
            return Response()

    monkeypatch.setattr(tools.aiohttp, "ClientSession", Client)
    return requested


@pytest.mark.parametrize("mime", ["application/pdf", DOCX, "image/png"])
async def test_document_mime_requires_explicit_opt_in(monkeypatch, mime):
    fake_http(monkeypatch, mime, [b"document"])
    with pytest.raises(AppError, match="PAGE_UNSUPPORTED"):
        await tools.fetch_public("https://example.com/file")
    assert await tools.fetch_public("https://example.com/file", documents=True) == (
        "https://example.com/file", b"document", mime,
    )


@pytest.mark.parametrize("mime,limit", [("text/plain", 2 * 1024**2), ("application/pdf", MAX_DOCUMENT_BYTES)])
@pytest.mark.parametrize("declared", [False, True])
async def test_fetch_enforces_text_and_document_size_limits(monkeypatch, mime, limit, declared):
    fake_http(monkeypatch, mime, [b"a" * limit, b"b"], limit + 1 if declared else None)
    with pytest.raises(AppError, match="PAGE_TOO_LARGE"):
        await tools.fetch_public("https://example.com/file", documents=True)


@pytest.mark.parametrize("mime", ["application/octet-stream", "application/zip", "application/x-zip-compressed"])
async def test_document_extension_recovers_generic_download_mime(monkeypatch, mime):
    fake_http(monkeypatch, mime, [b"zip archive"])
    url = "https://example.com/report%2EDOCX?download=1"
    assert (await tools.fetch_public(url, documents=True))[2] == DOCX
    with pytest.raises(AppError, match="PAGE_UNSUPPORTED"):
        await tools.fetch_public(url)
    with pytest.raises(AppError, match="PAGE_UNSUPPORTED"):
        await tools.fetch_public("https://example.com/unknown.bin", documents=True)


def document_bytes(mime):
    output = BytesIO()
    if mime == DOCX:
        document = Document()
        document.add_paragraph("Readable linked document")
        document.save(output)
    else:
        writer = PdfWriter()
        page = writer.add_blank_page(width=600, height=200)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                 NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 10 Tf 10 100 Td (Readable linked document with enough native text to avoid unnecessary OCR) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
        writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize("mime,extension", [("application/pdf", "pdf"), (DOCX, "docx")])
async def test_linked_document_uses_real_extraction_subprocess(monkeypatch, mime, extension):
    final_url = f"https://example.com/Annual%20Report.{extension}"

    async def fetch(url, *, documents=False):
        assert documents
        return final_url, document_bytes(mime), mime

    monkeypatch.setattr(tools, "fetch_public", fetch)
    result = await tools.read_url("https://example.com/download")
    assert "Readable linked document" in result["text"]
    assert result["url"] == final_url
    assert result["title"] == f"Annual Report.{extension}"
    assert result["format"] == mime
    assert result["scope"] == "page"
    assert result["truncated"] is False


@pytest.mark.parametrize("cancel", [False, True])
async def test_document_errors_and_cancellation_remove_temporary_files(monkeypatch, cancel):
    paths = []

    async def fetch(url, *, documents=False):
        return url, b"broken document", "application/pdf"

    async def extract(path, mime):
        paths.append(path)
        assert path.read_bytes() == b"broken document"
        if cancel:
            raise asyncio.CancelledError
        return {"error": "PDF_ENCRYPTED"}

    monkeypatch.setattr(tools, "fetch_public", fetch)
    monkeypatch.setattr(tools, "extract_file", extract)
    with pytest.raises(asyncio.CancelledError if cancel else AppError) as caught:
        await tools.read_url("https://example.com/document.pdf")
    if not cancel:
        assert "PDF_ENCRYPTED" in str(caught.value)
    assert len(paths) == 1
    assert not paths[0].parent.exists()


@pytest.mark.parametrize("mime,body,expected", [
    ("text/html", b"<title>Report</title><nav>menu</nav><main>Content<script>evil</script></main><footer>footer</footer>", "Content"),
    ("text/markdown", b"# Heading\n\nvalue < 5 and **bold**", "# Heading\n\nvalue < 5 and **bold**"),
    ("application/json", b'{"example": "<tag>keep</tag>"}', '{"example": "<tag>keep</tag>"}'),
])
async def test_html_main_extraction_and_plain_content_preservation(monkeypatch, mime, body, expected):
    async def fetch(url, *, documents=False):
        return url, body, mime

    monkeypatch.setattr(tools, "fetch_public", fetch)
    result = await tools.read_url("https://example.com/page")
    assert result["text"] == expected


async def test_search_unwraps_deduplicates_and_rejects_private_links(monkeypatch):
    html = b'''<div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Freport">Report</a><p class="result__snippet">Source excerpt</p></div>
    <a class="result__a" href="https://example.com/report">Duplicate</a>
    <a class="result__a" href="http://127.0.0.1/secret">Private</a>'''

    async def fetch(url):
        return url, html, "text/html"

    monkeypatch.setattr(tools, "fetch_public", fetch)
    result = await tools.search_web("research")
    assert result == [{"title": "Report", "url": "https://example.com/report",
                       "text": "Source excerpt", "scope": "search_snippet", "truncated": False}]


@pytest.mark.parametrize("failure", [False, True])
async def test_search_uses_lite_when_html_is_empty_or_unavailable(monkeypatch, failure):
    requested = []

    async def fetch(url):
        requested.append(url)
        if "html.duckduckgo.com" in url:
            if failure:
                raise AppError("PAGE_UNAVAILABLE", "unavailable")
            return url, b"<html>No results</html>", "text/html"
        return url, b'<a class="result-link" href="https://example.com/fallback">Fallback</a>', "text/html"

    monkeypatch.setattr(tools, "fetch_public", fetch)
    assert (await tools.search_web("a & b"))[0]["url"] == "https://example.com/fallback"
    assert len(requested) == 2
    assert "q=a+%26+b" in requested[0]


async def test_search_reports_both_endpoints_unavailable(monkeypatch):
    requested = []

    async def fetch(url):
        requested.append(url)
        raise AppError("PAGE_UNSUPPORTED", "binary response")

    monkeypatch.setattr(tools, "fetch_public", fetch)
    with pytest.raises(AppError, match="SEARCH_UNAVAILABLE"):
        await tools.search_web("research")
    assert len(requested) == 2
