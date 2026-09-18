import pytest
from modurouter.extract import extract
from modurouter.files import storage_path
from PIL import Image
from pypdf import PdfWriter


def test_korean_txt_and_truncation(tmp_path):
    path = tmp_path / "korean.txt"
    path.write_text("안녕하세요. 파일을 요약해 주세요. " * 2000)
    result = extract(path, "text/plain")
    assert result["text"].startswith("안녕하세요")
    assert len(result["text"]) == 20000 and result["truncated"]


def test_binary_text_rejected(tmp_path):
    path = tmp_path / "fake.txt"
    path.write_bytes(b"hello\0binary")
    with pytest.raises(ValueError, match="FILE_ENCODING_INVALID"):
        extract(path, "text/plain")


def test_pdf_page_limit_and_encryption(tmp_path):
    path = tmp_path / "pages.pdf"
    writer = PdfWriter()
    for _ in range(21):
        writer.add_blank_page(width=200, height=200)
    writer.write(path)
    with pytest.raises(ValueError, match="PDF_PAGE_LIMIT"):
        extract(path, "application/pdf")
    writer.encrypt("password")
    writer.write(path)
    with pytest.raises(ValueError, match="PDF_ENCRYPTED"):
        extract(path, "application/pdf")


def test_scanned_pdf_no_text_is_failure(tmp_path):
    path = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(path)
    with pytest.raises(ValueError, match="NO_EXTRACTABLE_TEXT"):
        extract(path, "application/pdf")


def test_image_pixel_limit(tmp_path):
    path = tmp_path / "oversized.png"
    Image.new("1", (5000, 4001)).save(path)
    with pytest.raises(ValueError, match="IMAGE_PIXEL_LIMIT"):
        extract(path, "image/png")


def test_storage_paths_never_escape():
    with pytest.raises(ValueError):
        storage_path("../../etc/passwd")
    with pytest.raises(ValueError):
        storage_path("/etc/passwd")


def test_pdf_with_repairable_xref_keeps_text(tmp_path):
    import re

    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    path = tmp_path / "repairable.pdf"
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 10 100 Td (Readable document) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(path)
    path.write_bytes(re.sub(rb"startxref\s+\d+", b"startxref\n0", path.read_bytes()))
    assert "Readable document" in extract(path, "application/pdf")["text"]
