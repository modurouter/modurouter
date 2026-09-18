"""Inert, bounded extraction for plain text, Markdown, delimited text and HTML."""

import codecs
import csv
import io
import json
from html.parser import HTMLParser
from pathlib import Path

from .document_formats import MAX_DOCUMENT_BYTES, MAX_TEXT

TEXT_DOCUMENT_MIMES = {
    "text/plain", "text/markdown", "text/csv", "text/tab-separated-values",
    "text/html", "application/xhtml+xml",
}
ERRORS = {"FILE_ENCODING_INVALID", "FILE_TOO_LARGE", "TEXT_DOCUMENT_INVALID", "TEXT_DOCUMENT_LIMIT"}


class _TextBuffer:
    def __init__(self):
        self.parts: list[str] = []
        self.size = 0

    @property
    def full(self) -> bool:
        return self.size >= MAX_TEXT + 1

    def add(self, value: str) -> None:
        value = value[:max(0, MAX_TEXT + 1 - self.size)]
        if value:
            self.parts.append(value)
            self.size += len(value)

    def value(self) -> str:
        return "".join(self.parts)


def _decode(path: Path) -> str:
    with path.open("rb") as handle:
        data = handle.read(MAX_DOCUMENT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError("FILE_TOO_LARGE")
    # BOM detection precedes the binary check: UTF-16 Korean text contains NUL bytes.
    if data.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        candidates = ("utf-32",)
    elif data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        candidates = ("utf-16",)
    elif data.startswith(codecs.BOM_UTF8):
        candidates = ("utf-8-sig",)
    else:
        candidates = ("utf-8", "cp949")
    for encoding in candidates:
        try:
            text = data.decode(encoding, errors="strict")
        except UnicodeError:
            continue
        if any((ord(char) < 32 and char not in "\t\n\r\f") or 127 <= ord(char) <= 159
               for char in text):
            raise ValueError("FILE_ENCODING_INVALID")
        return text
    raise ValueError("FILE_ENCODING_INVALID")


def _column_name(number: int) -> str:
    letters = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _delimited(text: str, delimiter: str) -> str:
    # The input itself is bounded; allow an individual quoted field up to that bound.
    csv.field_size_limit(MAX_DOCUMENT_BYTES)
    result = _TextBuffer()
    try:
        for row_number, row in enumerate(csv.reader(io.StringIO(text, newline=""),
                                                  delimiter=delimiter, strict=True), 1):
            if not row or not any(value.strip() for value in row):
                continue
            result.add(f"[행 {row_number}] ")
            for column, value in enumerate(row, 1):
                if column > 1:
                    result.add(" | ")
                result.add(f"{_column_name(column)}{row_number}=")
                # Quotes disambiguate separators, formulas and embedded line breaks.
                result.add(json.dumps(value, ensure_ascii=False))
                if result.full:
                    return result.value()
            result.add("\n")
            if result.full:
                break
    except csv.Error as exc:
        raise ValueError("TEXT_DOCUMENT_INVALID") from exc
    return result.value()


class _HTMLText(HTMLParser):
    _SKIP = {"head", "script", "style", "noscript", "template", "iframe", "object",
             "embed", "svg", "canvas"}
    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
             "meta", "param", "source", "track", "wbr"}
    _BLOCK = {"address", "article", "aside", "blockquote", "div", "dl", "dt", "dd",
              "fieldset", "figcaption", "figure", "footer", "header", "main", "nav",
              "ol", "p", "section", "ul", "pre", "form"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.output = _TextBuffer()
        self.stack: list[tuple[str, bool]] = []
        self.tables: list[list[int]] = []
        self.table_number = 0
        self.has_content = False

    def _hidden(self) -> bool:
        return bool(self.stack and self.stack[-1][1])

    def handle_starttag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        attrs = dict(attributes)
        style = "".join((attrs.get("style") or "").lower().split())
        hidden = (self._hidden() or tag in self._SKIP or "hidden" in attrs
                  or (attrs.get("aria-hidden") or "").lower() == "true"
                  or "display:none" in style or "visibility:hidden" in style)
        if tag not in self._VOID:
            if len(self.stack) >= 256:
                raise ValueError("TEXT_DOCUMENT_LIMIT")
            self.stack.append((tag, hidden))
        if hidden:
            return
        if tag in self._BLOCK or tag in {"br", "hr"}:
            self.output.add("\n")
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.output.add("\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self.output.add("\n- ")
        elif tag == "table":
            self.table_number += 1
            self.tables.append([self.table_number, 0, 0])
            self.output.add(f"\n[표 {self.table_number}]\n")
        elif tag == "tr" and self.tables:
            self.tables[-1][1] += 1
            self.tables[-1][2] = 0
            self.output.add(f"\n[행 {self.tables[-1][1]}] ")
        elif tag in {"td", "th"} and self.tables:
            table = self.tables[-1]
            table[2] += 1
            self.output.add(f"[열 {table[2]}")
            for attribute, label in (("rowspan", "행 병합"), ("colspan", "열 병합")):
                value = attrs.get(attribute, "1") or "1"
                if value.isdecimal() and 1 < int(value[:6]) <= 10000:
                    self.output.add(f", {label} {value[:6]}")
            self.output.add("] ")
        elif tag == "img":
            alt = " ".join((attrs.get("alt") or "").split())
            self.output.add(f"[이미지 대체 텍스트: {alt}]" if alt else "[이미지: 내용 추출 제외]")
            self.has_content = True
        elif tag in {"input", "textarea"}:
            # Static input values are useful in exported forms. Passwords are excluded.
            if (attrs.get("type") or "").lower() not in {"hidden", "password"}:
                value = attrs.get("value")
                if value:
                    self.output.add(value)
                    self.has_content = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self._VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        hidden = self._hidden()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break
        if hidden:
            return
        if tag == "table" and self.tables:
            self.tables.pop()
            self.output.add("\n")
        elif tag in {"td", "th"}:
            self.output.add(" | ")
        elif tag in self._BLOCK or tag in {"tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self.output.add("\n")

    def handle_data(self, data: str) -> None:
        if self._hidden():
            return
        self.has_content = self.has_content or bool(data.strip())
        if any(tag == "pre" for tag, _ in self.stack):
            self.output.add(data)
        else:
            # Preserve boundary spaces between inline tags without joining adjacent words.
            self.output.add(" ".join(data.split()) if not data else
                            (" " if data[0].isspace() else "") + " ".join(data.split())
                            + (" " if data[-1].isspace() else ""))


def text_document(path: Path, mime: str) -> str:
    """Return at most MAX_TEXT + 1 chars; the extra char signals truncation upstream."""
    if mime not in TEXT_DOCUMENT_MIMES:
        raise ValueError("FILE_UNSUPPORTED")
    text = _decode(path)
    if mime in {"text/plain", "text/markdown"}:
        return text[:MAX_TEXT + 1]
    if mime in {"text/csv", "text/tab-separated-values"}:
        return _delimited(text, "," if mime == "text/csv" else "\t")
    parser = _HTMLText()
    for offset in range(0, len(text), 4096):
        parser.feed(text[offset:offset + 4096])
        if parser.output.full:
            break
    if not parser.output.full:
        parser.close()
    return parser.output.value() if parser.has_content else ""
