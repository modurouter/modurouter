"""Bounded, local text extraction for HWP 5 and HWPX.

Format references: https://tech.hancom.com/python-hwp-parsing-2/
and https://tech.hancom.com/hwpxformat/. Never use PrvText: it is only a preview.
"""

import re
import struct
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from xml.etree.ElementTree import ParseError

import olefile
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from defusedxml import ElementTree as XML
from defusedxml.common import DefusedXmlException

HWP_MIME = "application/x-hwp"
HWPX_MIME = "application/hwp+zip"
MAX_MEMBER = 16 * 1024**2
MAX_EXPANDED = 64 * 1024**2
MAX_ENTRIES = 4096
SIGNATURE = b"HWP Document File" + b"\0" * 15
PARA_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
SECTION_NS = "http://www.hancom.co.kr/hwpml/2011/section"
OPF_NS = "http://www.idpf.org/2007/opf/"
ERRORS = {"HWP_INVALID", "HWP_ENCRYPTED", "HWP_PROTECTED", "HWP_VERSION_UNSUPPORTED",
          "HWP_SIZE_LIMIT"}


def _stream(ole, name):
    if ole.get_size(name) > MAX_MEMBER:
        raise ValueError("HWP_SIZE_LIMIT")
    return ole.openstream(name).read()


def _header(ole):
    if not ole.exists("FileHeader"):
        raise ValueError("FILE_TYPE_MISMATCH")
    header = _stream(ole, "FileHeader")
    if header[:32] != SIGNATURE:
        raise ValueError("FILE_TYPE_MISMATCH")
    if len(header) != 256:
        raise ValueError("HWP_INVALID")
    return header


def _package(archive):
    entries = archive.infolist()
    names = {entry.filename for entry in entries}
    if len(entries) > MAX_ENTRIES or sum(entry.file_size for entry in entries) > MAX_EXPANDED:
        raise ValueError("HWP_SIZE_LIMIT")
    if len(names) != len(entries):
        raise ValueError("HWP_INVALID")
    if any(entry.flag_bits & 1 for entry in entries):
        raise ValueError("HWP_ENCRYPTED")
    if "mimetype" not in names or "Contents/content.hpf" not in names:
        raise ValueError("FILE_TYPE_MISMATCH")
    if archive.getinfo("mimetype").file_size > 128:
        raise ValueError("FILE_TYPE_MISMATCH")
    if archive.read("mimetype").strip() != HWPX_MIME.encode():
        raise ValueError("FILE_TYPE_MISMATCH")
    return names


def validate_container(path: Path, mime: str):
    """Inspect the actual container, independent of browser and libmagic MIME guesses."""
    try:
        if mime == HWP_MIME:
            with path.open("rb") as handle:
                if handle.read(30).startswith(b"HWP Document File V3.00"):
                    raise ValueError("HWP_VERSION_UNSUPPORTED")
            with olefile.OleFileIO(path) as ole:
                _header(ole)
        else:
            with zipfile.ZipFile(path) as archive:
                _package(archive)
    except (OSError, zipfile.BadZipFile, KeyError, NotImplementedError) as exc:
        raise ValueError("FILE_TYPE_MISMATCH") from exc


def _inflate(data, *, padded=False):
    inflater = zlib.decompressobj(-15)
    result = inflater.decompress(data, MAX_MEMBER + 1)
    if len(result) > MAX_MEMBER or inflater.unconsumed_tail:
        raise ValueError("HWP_SIZE_LIMIT")
    # Some Hancom writers append a gzip CRC/size trailer to raw deflate.
    trailing = inflater.unused_data
    if trailing[:8] == struct.pack("<II", zlib.crc32(result), len(result)):
        trailing = trailing[8:]
    # Distributed sections are padded to an AES block boundary.
    if not inflater.eof or (trailing and not (padded and len(trailing) < 16)):
        raise ValueError("HWP_INVALID")
    return result


def _distribution(data):
    """Decode the public reading key carried by a distribution document section."""
    if len(data) < 276 or struct.unpack_from("<I", data)[0] != (256 << 20) | 28:
        raise ValueError("HWP_INVALID")
    header = bytearray(data[4:260])
    seed = struct.unpack_from("<I", header)[0]
    state, remaining, mask = seed, 0, 0
    for index in range(256):
        if remaining == 0:
            state = (214013 * state + 2531011) & 0xFFFFFFFF
            mask = (state >> 16) & 255
            state = (214013 * state + 2531011) & 0xFFFFFFFF
            remaining = ((state >> 16) & 15) + 1
        if index >= 4:
            header[index] ^= mask
        remaining -= 1
    offset = 4 + (seed & 15)
    decryptor = Cipher(algorithms.AES(bytes(header[offset:offset + 16])), modes.ECB()).decryptor()
    return decryptor.update(data[260:]) + decryptor.finalize()


def _records(data, *, padded=False):
    offset = 0
    while offset < len(data):
        if padded and len(data) - offset < 16 and not any(data[offset:]):
            break
        if len(data) - offset < 4:
            raise ValueError("HWP_INVALID")
        header = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        size = header >> 20
        if size == 4095:
            if len(data) - offset < 4:
                raise ValueError("HWP_INVALID")
            size = struct.unpack_from("<I", data, offset)[0]
            offset += 4
        if size > len(data) - offset:
            raise ValueError("HWP_INVALID")
        yield header & 1023, data[offset:offset + size]
        offset += size


def _paragraph(data):
    if len(data) % 2:
        raise ValueError("HWP_INVALID")
    result = bytearray()
    offset = 0
    while offset < len(data):
        code = struct.unpack_from("<H", data, offset)[0]
        if code >= 32:
            result.extend(data[offset:offset + 2])
            offset += 2
        elif code in {0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31}:
            replacement = {10: "\n", 13: "\n", 24: "-", 30: " ", 31: " "}.get(code, "")
            result.extend(replacement.encode("utf-16le"))
            offset += 2
        else:
            if offset + 16 > len(data):
                raise ValueError("HWP_INVALID")
            if code == 9:
                result.extend(b"\t\0")
            elif code in {11, 15, 16, 17}:
                result.extend(b"\n\0")
            offset += 16
    return result.decode("utf-16le").rstrip("\n")


def _hwp(path):
    with olefile.OleFileIO(path) as ole:
        header = _header(ole)
        if header[35] != 5:
            raise ValueError("HWP_VERSION_UNSUPPORTED")
        flags = struct.unpack_from("<I", header, 36)[0]
        if flags & (2 | 256):
            raise ValueError("HWP_ENCRYPTED")
        if flags & (16 | 1024):
            raise ValueError("HWP_PROTECTED")
        root = "ViewText" if flags & 4 else "BodyText"
        sections = [name for name in ole.listdir() if len(name) == 2
                    and name[0] == root and re.fullmatch(r"Section\d+", name[1])]
        sections.sort(key=lambda name: int(name[1][7:]))
        if not sections or [int(name[1][7:]) for name in sections] != list(range(len(sections))):
            raise ValueError("HWP_INVALID")
        info = _stream(ole, "DocInfo")
        if flags & 1:
            info = _inflate(info)
        properties = next(_records(info), None)
        if not properties or properties[0] != 16 or len(properties[1]) < 2:
            raise ValueError("HWP_INVALID")
        if struct.unpack_from("<H", properties[1])[0] != len(sections):
            raise ValueError("HWP_INVALID")
        total, paragraphs = 0, []
        for name in sections:
            data = _stream(ole, name)
            if flags & 4:
                data = _distribution(data)
            if flags & 1:
                data = _inflate(data, padded=bool(flags & 4))
            total += len(data)
            if total > MAX_EXPANDED:
                raise ValueError("HWP_SIZE_LIMIT")
            for tag, payload in _records(data, padded=bool(flags & 4 and not flags & 1)):
                if tag == 67:
                    paragraphs.append(_paragraph(payload))
                elif tag == 88:  # Equation source, stored as a length-prefixed UTF-16 string.
                    if len(payload) < 6:
                        raise ValueError("HWP_INVALID")
                    end = 6 + 2 * struct.unpack_from("<H", payload, 4)[0]
                    if end > len(payload):
                        raise ValueError("HWP_INVALID")
                    paragraphs.append(payload[6:end].decode("utf-16le"))
        return "\n".join(paragraphs)


def _xml(archive, name):
    if archive.getinfo(name).file_size > MAX_MEMBER:
        raise ValueError("HWP_SIZE_LIMIT")
    # Check depth and count while constructing the tree to bound hostile XML.
    depth, count, root = 0, 0, None
    with archive.open(name) as handle:
        for event, node in XML.iterparse(handle, events=("start", "end"), forbid_dtd=True):
            if event == "start":
                root = node if root is None else root
                depth += 1
                count += 1
                if depth > 128 or count > 200_000:
                    raise ValueError("HWP_SIZE_LIMIT")
            else:
                depth -= 1
    return root


def _section_text(node):
    tag = node.tag
    if tag == f"{{{PARA_NS}}}t":
        # Text runs can contain inline tabs and breaks with text in their tails.
        pieces = [node.text or ""]
        for child in node:
            pieces.extend((_section_text(child), child.tail or ""))
        return "".join(pieces)
    if tag == f"{{{PARA_NS}}}tab":
        return "\t"
    if tag == f"{{{PARA_NS}}}lineBreak":
        return "\n"
    if tag in {f"{{{PARA_NS}}}nbSpace", f"{{{PARA_NS}}}fwSpace"}:
        return " "
    if tag == f"{{{PARA_NS}}}hyphen":
        return "-"
    if tag == f"{{{PARA_NS}}}script":
        return node.text or ""
    pieces = [_section_text(child) for child in node]
    if tag == f"{{{PARA_NS}}}tr":
        return "\t".join(piece.strip("\n") for piece in pieces) + "\n"
    text = "".join(pieces)
    if tag == f"{{{PARA_NS}}}tbl" and text:
        text = "\n" + text
    if tag in {f"{{{PARA_NS}}}p", f"{{{PARA_NS}}}tbl"} and text and not text.endswith("\n"):
        text += "\n"
    return text


def _hwpx(path):
    with zipfile.ZipFile(path) as archive:
        names = _package(archive)
        package = _xml(archive, "Contents/content.hpf")
        if package.tag != f"{{{OPF_NS}}}package":
            raise ValueError("HWP_INVALID")
        items = {}
        for item in package.findall(f"{{{OPF_NS}}}manifest/{{{OPF_NS}}}item"):
            href = item.get("href", "")
            relative = PurePosixPath(href)
            if relative.is_absolute() or ".." in relative.parts or "\\" in href or ":" in href:
                raise ValueError("HWP_INVALID")
            # Hancom writes package-root paths; other writers use OPF-relative paths.
            name = href if href in names else "Contents/" + href
            identifier = item.get("id")
            if not identifier or identifier in items:
                raise ValueError("HWP_INVALID")
            items[identifier] = name
        sections, seen = [], set()
        for ref in package.findall(f"{{{OPF_NS}}}spine/{{{OPF_NS}}}itemref"):
            name = items.get(ref.get("idref"))
            if name not in names or name in seen:
                raise ValueError("HWP_INVALID")
            seen.add(name)
            document = _xml(archive, name)
            if document.tag == f"{{{SECTION_NS}}}sec":
                sections.append(_section_text(document))
            elif document.tag != "{http://www.hancom.co.kr/hwpml/2011/head}head":
                raise ValueError("HWP_INVALID")
        declared_sections = {name for name in items.values()
                             if re.fullmatch(r"Contents/section\d+\.xml", name)}
        if not declared_sections.issubset(seen):
            raise ValueError("HWP_INVALID")
        if not sections:
            raise ValueError("HWP_INVALID")
        return "\n".join(sections)


def hangul_text(path: Path, mime: str):
    try:
        validate_container(path, mime)
        return _hwp(path) if mime == HWP_MIME else _hwpx(path)
    except ValueError as exc:
        if str(exc) in ERRORS:
            raise
        raise ValueError("HWP_INVALID") from exc
    except (OSError, KeyError, struct.error, zlib.error, zipfile.BadZipFile,
            ParseError, DefusedXmlException, RuntimeError, NotImplementedError) as exc:
        raise ValueError("HWP_INVALID") from exc
