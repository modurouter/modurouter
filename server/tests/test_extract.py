import pytest
from modurouter.document_formats import MAX_TEXT
from modurouter.extract import extract
from modurouter.files import storage_path
from PIL import Image
from pypdf import PdfWriter


def test_korean_txt_and_truncation(tmp_path):
    path = tmp_path / "korean.txt"
    path.write_text("안녕하세요. 파일을 요약해 주세요. " * 8000)
    result = extract(path, "text/plain")
    assert result["text"].startswith("안녕하세요")
    assert len(result["text"]) == MAX_TEXT and result["truncated"]


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


def test_korean_notice_ocr_preserves_every_line():
    import shutil
    import subprocess
    from pathlib import Path

    if not shutil.which("tesseract"):
        pytest.skip("Tesseract is required for the real OCR regression")
    languages = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, check=True).stdout.splitlines()
    if "kor" not in languages:
        pytest.skip("Korean Tesseract data is required")
    result = extract(Path(__file__).parent / "fixtures/korean-notice.png", "image/png")
    compact = "".join(result["text"].split())
    for line in ["해커톤 안내문", "행사명: 모두라우터 데모", "장소: 파란 강의실", "시작 시간: 오후 2시"]:
        assert "".join(line.split()) in compact


@pytest.mark.parametrize("confidence,block_text,expected", [
    (95, "longer block text", "left column\nright column"),
    (20, "unreliable", "OCR_LOW_CONFIDENCE"),
])
def test_ocr_keeps_automatic_layout_unless_block_recovers_more(tmp_path, monkeypatch, confidence, block_text, expected):
    from types import SimpleNamespace

    from modurouter.extract import image_text

    def run(command, **kwargs):
        from pathlib import Path

        output = Path(command[2])
        text = "left column\nright column" if command[command.index("--psm") + 1] == "3" else block_text
        output.with_suffix(".txt").write_text(text)
        output.with_suffix(".tsv").write_text("level\tconf\ttext\n" + f"5\t{confidence}\t{text.replace(chr(10), ' ')}\n")
        assert 0 < kwargs["timeout"] <= 20
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("modurouter.extract.subprocess.run", run)
    if expected == "OCR_LOW_CONFIDENCE":
        with pytest.raises(ValueError, match=expected):
            image_text(tmp_path / "image.png")
    else:
        assert image_text(tmp_path / "image.png") == expected


def add_native_pdf_text(writer, page, text, y=100):
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    resources = page.get('/Resources', DictionaryObject())
    resources[NameObject('/Font')] = DictionaryObject({NameObject('/F1'): font})
    page[NameObject('/Resources')] = resources
    stream = DecodedStreamObject()
    stream.set_data(f'BT /F1 18 Tf 10 {y} Td ({text}) Tj ET'.encode())
    from pypdf.generic import ArrayObject
    previous = page.get('/Contents')
    page[NameObject('/Contents')] = ArrayObject([previous, writer._add_object(stream)]) if previous else writer._add_object(stream)


def test_short_native_pdf_needs_no_ocr_and_is_not_marked_partial(tmp_path, monkeypatch):
    writer = PdfWriter()
    add_native_pdf_text(writer, writer.add_blank_page(width=200, height=200), 'Short note')
    path = tmp_path / 'short.pdf'
    writer.write(path)

    def unexpected(*args, **kwargs):
        pytest.fail('A complete native-text page must not need OCR')

    monkeypatch.setattr('modurouter.extract.image_text', unexpected)
    result = extract(path, 'application/pdf')
    assert 'Short note' in result['text'] and not result['truncated']


@pytest.mark.parametrize('mixed_same_page', [False, True])
def test_real_korean_scanned_pdf_and_mixed_native_text(tmp_path, mixed_same_page):
    import shutil
    import subprocess
    from pathlib import Path

    from pypdf import PdfReader

    if not shutil.which('tesseract'):
        pytest.skip('Tesseract is required for real PDF OCR')
    languages = subprocess.run(['tesseract', '--list-langs'], capture_output=True, text=True, check=True).stdout.splitlines()
    if 'kor' not in languages:
        pytest.skip('Korean Tesseract data is required')
    scan = tmp_path / 'scan.pdf'
    with Image.open(Path(__file__).parent / 'fixtures/korean-notice.png') as image:
        image.convert('RGB').save(scan, 'PDF', resolution=72)
    writer = PdfWriter()
    native = 'Native document heading with enough text to exceed forty characters'
    if not mixed_same_page:
        add_native_pdf_text(writer, writer.add_blank_page(width=900, height=200), native)
    scanned_page = writer.add_page(PdfReader(scan).pages[0])
    if mixed_same_page:
        top = float(scanned_page.mediabox.top)
        scanned_page.mediabox.top = top + 80
        add_native_pdf_text(writer, scanned_page, native, top + 30)
    combined = tmp_path / 'extensionless-storage-key'
    writer.write(combined)
    result = extract(combined, 'application/pdf')
    compact = ''.join(result['text'].split())
    for line in ['해커톤 안내문', '행사명: 모두라우터 데모', '장소: 파란 강의실', '시작 시간: 오후 2시', native]:
        assert ''.join(line.split()) in compact
    assert not result['truncated']


def test_pdf_partial_ocr_failure_preserves_native_text(tmp_path, monkeypatch):
    writer = PdfWriter()
    native = 'Native text that is readable and long enough to skip OCR automatically.'
    add_native_pdf_text(writer, writer.add_blank_page(width=900, height=200), native)
    writer.add_blank_page(width=200, height=200)
    path = tmp_path / 'mixed.pdf'
    writer.write(path)

    def failed_ocr(*args, **kwargs):
        raise ValueError('OCR_LOW_CONFIDENCE')

    monkeypatch.setattr('modurouter.extract.image_text', failed_ocr)
    result = extract(path, 'application/pdf')
    assert native in result['text']
    assert '완료하지 못했습니다: 2' in result['text']
    assert result['truncated']


def test_pdf_ocr_timeout_is_reported(tmp_path, monkeypatch):
    import subprocess
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    path = tmp_path / 'scan.pdf'
    writer.write(path)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('tesseract', 20)

    monkeypatch.setattr('modurouter.extract.image_text', timeout)
    with pytest.raises(ValueError, match='OCR_TIMEOUT'):
        extract(path, 'application/pdf')
