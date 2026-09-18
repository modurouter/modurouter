import json
import subprocess
import sys

import pytest
from hangul_fixtures import compound, hwp, hwpx, paragraph, record
from modurouter.extract import extract
from modurouter.hangul import HWP_MIME, HWPX_MIME, validate_container


def document(tmp_path, content):
    path = tmp_path / "extensionless-storage-key"
    path.write_bytes(content)
    return path


@pytest.mark.parametrize("flags", [0, 1, 4, 5])
@pytest.mark.parametrize("trailer", [False, True])
def test_hwp_compression_distribution_nested_paragraphs_and_sections(tmp_path, flags, trailer):
    text = "본문😀\t탭\n둘째 줄".replace("\t", "\t" + "\0" * 6 + "\t")
    first = paragraph(text) + paragraph("표 셀 내용", 3) + paragraph("각주 내용", 3)
    sections = [first, *[paragraph(f"구역 {i}") for i in range(1, 12)]]
    result = extract(document(tmp_path, hwp(sections, flags=flags, trailer=trailer)), HWP_MIME)
    assert result == {"text": "본문😀\t탭\n둘째 줄\n표 셀 내용\n각주 내용\n" +
                      "\n".join(f"구역 {i}" for i in range(1, 12)), "truncated": False}


def test_hwp_extended_record_and_truncation(tmp_path):
    result = extract(document(tmp_path, hwp([paragraph("한" * 21000)])), HWP_MIME)
    assert result == {"text": "한" * 20000, "truncated": True}


def test_hwp_control_payload_is_not_decoded_as_text(tmp_path):
    control = "\x02" + "쓰레기문자값" + "\x02"
    text = control + "이름" + "\x19" + "\x1e" + "홍길동"
    result = extract(document(tmp_path, hwp([paragraph(text)])), HWP_MIME)
    assert result["text"] == "이름 홍길동"


def test_hwp_equation_source(tmp_path):
    equation = "a^2 + b^2 = c^2"
    payload = b"\0" * 4 + len(equation).to_bytes(2, "little") + equation.encode("utf-16le")
    result = extract(document(tmp_path, hwp([paragraph("수식") + record(88, payload)])), HWP_MIME)
    assert equation in result["text"]


@pytest.mark.parametrize("flags,version,error", [
    (2, 5, "HWP_ENCRYPTED"), (256, 5, "HWP_ENCRYPTED"),
    (16, 5, "HWP_PROTECTED"), (1024, 5, "HWP_PROTECTED"),
    (0, 6, "HWP_VERSION_UNSUPPORTED"),
])
def test_hwp_specific_errors(tmp_path, flags, version, error):
    with pytest.raises(ValueError, match=error):
        extract(document(tmp_path, hwp(flags=flags, version=version)), HWP_MIME)


@pytest.mark.parametrize("payload", [b"\x01", record(67, b"x"), record(67, b"\x02\0"),
                                     b"\x43\0\xf0\xff", b"\x43\0\x10\x01"])
def test_hwp_corruption_does_not_return_partial_success(tmp_path, payload):
    with pytest.raises(ValueError, match="HWP_INVALID"):
        extract(document(tmp_path, hwp([paragraph("정상 앞부분") + payload])), HWP_MIME)


@pytest.mark.parametrize("mime,content", [
    (HWP_MIME, b"not an hwp"), (HWP_MIME, compound({"WordDocument": b"fake doc"})),
    (HWPX_MIME, hwpx(extra={"mimetype": "application/zip"})),
    (HWPX_MIME, b"not a zip"),
])
def test_false_extension_rejected(tmp_path, mime, content):
    with pytest.raises(ValueError, match="FILE_TYPE_MISMATCH"):
        validate_container(document(tmp_path, content), mime)


def test_legacy_hwp_explains_conversion(tmp_path):
    with pytest.raises(ValueError, match="HWP_VERSION_UNSUPPORTED"):
        validate_container(document(tmp_path, b"HWP Document File V3.00"), HWP_MIME)


@pytest.mark.parametrize("relative", [False, True])
def test_hwpx_spine_order_tables_textboxes_breaks_and_equations(tmp_path, relative):
    body = ('<hp:p><hp:run><hp:t>표 앞</hp:t><hp:tbl><hp:tr>'
            '<hp:tc><hp:subList><hp:p><hp:run><hp:t>이름</hp:t></hp:run></hp:p></hp:subList></hp:tc>'
            '<hp:tc><hp:subList><hp:p><hp:run><hp:t>홍길동</hp:t></hp:run></hp:p></hp:subList></hp:tc>'
            '</hp:tr></hp:tbl><hp:t>표 뒤< hp:tab/>다음< hp:lineBreak/>줄😀</hp:t>'
            '<hp:rect><hp:drawText><hp:subList><hp:p><hp:run><hp:t>글상자</hp:t></hp:run>'
            '</hp:p></hp:subList></hp:drawText></hp:rect>'
            '<hp:equation><hp:script>x^2</hp:script></hp:equation></hp:run></hp:p>').replace('< hp:', '<hp:')
    data = hwpx([body, '<hp:p><hp:run><hp:t>첫 구역</hp:t></hp:run></hp:p>'], [1, 0], relative=relative)
    result = extract(document(tmp_path, data), HWPX_MIME)
    assert result["text"].startswith("첫 구역\n")
    assert "이름\t홍길동" in result["text"]
    assert "표 뒤\t다음\n줄😀" in result["text"]
    assert result["text"].count("글상자") == 1
    assert "x^2" in result["text"] and "오래된 미리보기" not in result["text"]


@pytest.mark.parametrize("content,mime", [(hwp([paragraph("")]), HWP_MIME), (hwpx([""]), HWPX_MIME)])
def test_empty_document_is_not_success(tmp_path, content, mime):
    with pytest.raises(ValueError, match="NO_EXTRACTABLE_TEXT"):
        extract(document(tmp_path, content), mime)


def test_hwpx_missing_or_duplicate_spine_references(tmp_path):
    for order in ([], [0, 0], [4]):
        with pytest.raises(ValueError, match="HWP_INVALID"):
            extract(document(tmp_path, hwpx(order=order)), HWPX_MIME)


def test_hwpx_inline_spaces_keep_words_separate(tmp_path):
    body = '<hp:p><hp:run><hp:t>묶음<hp:nbSpace/>빈칸<hp:fwSpace/>고정<hp:hyphen/>폭</hp:t></hp:run></hp:p>'
    assert extract(document(tmp_path, hwpx([body])), HWPX_MIME)["text"] == "묶음 빈칸 고정-폭\n"


@pytest.mark.parametrize("xml", [
    '<!DOCTYPE sec [<!ENTITY secret SYSTEM "file:///etc/passwd">]><sec>&secret;</sec>',
    '<broken>', '<not-a-section/>',
])
def test_hwpx_rejects_entities_and_malformed_sections(tmp_path, xml):
    with pytest.raises(ValueError, match="HWP_INVALID"):
        extract(document(tmp_path, hwpx(extra={"Contents/section0.xml": xml})), HWPX_MIME)


def test_hwpx_rejects_excessive_nesting(tmp_path):
    with pytest.raises(ValueError, match="HWP_SIZE_LIMIT"):
        extract(document(tmp_path, hwpx(["<hp:p>" * 130 + "</hp:p>" * 130])), HWPX_MIME)


@pytest.mark.parametrize("content,mime", [(hwp([paragraph("한" * 1000)]), HWP_MIME),
                                         (hwpx(["<hp:p>" + "한" * 1000 + "</hp:p>"]), HWPX_MIME)])
def test_expansion_is_bounded(tmp_path, monkeypatch, content, mime):
    monkeypatch.setattr("modurouter.hangul.MAX_MEMBER", 1024)
    with pytest.raises(ValueError, match="HWP_SIZE_LIMIT"):
        extract(document(tmp_path, content), mime)


@pytest.mark.parametrize("content,mime,expected", [
    (hwp(), HWP_MIME, {"text": "한글 문서 본문", "truncated": False}),
    (hwpx(), HWPX_MIME, {"text": "한글 문서 본문\n", "truncated": False}),
    (hwp(flags=2), HWP_MIME, {"error": "HWP_ENCRYPTED"}),
])
def test_real_extractor_subprocess_contract(tmp_path, content, mime, expected):
    path = document(tmp_path, content)
    result = subprocess.run([sys.executable, "-m", "modurouter.extract", str(path), mime],
                            capture_output=True, text=True, check=True, timeout=30)
    assert json.loads(result.stdout) == expected
