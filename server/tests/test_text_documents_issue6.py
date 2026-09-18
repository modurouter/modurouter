import codecs

import pytest
from modurouter import text_documents
from modurouter.text_documents import text_document


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "cp949"])
@pytest.mark.parametrize("mime", ["text/plain", "text/markdown"])
def test_korean_encodings_preserve_markdown_and_order(tmp_path, encoding, mime):
    original = "# 회의록\n\n첫 문단입니다.\n\n| 항목 | 금액 |\n| --- | --- |\n| 한글 | 300원 |\n\n마지막 사실"
    path = tmp_path / "document"
    path.write_bytes(original.encode(encoding))
    assert text_document(path, mime) == original


@pytest.mark.parametrize("data", [b"hello\0binary", b"\xff", b"hello\x1b[31m", codecs.BOM_UTF16_LE + b"a"])
def test_invalid_encoding_and_binary_rejected(tmp_path, data):
    path = tmp_path / "document"
    path.write_bytes(data)
    with pytest.raises(ValueError, match="FILE_ENCODING_INVALID"):
        text_document(path, "text/plain")


def test_csv_preserves_headers_quoted_multiline_cells_and_formulas(tmp_path):
    path = tmp_path / "document"
    path.write_bytes('제품,금액,비고\r\n"한국,제품",1250,"첫째 줄\n둘째 줄"\r\n마지막,=SUM(B2:B2),"따옴표 ""값"""'.encode("cp949"))
    result = text_document(path, "text/csv")
    assert '[행 1] A1="제품" | B1="금액" | C1="비고"' in result
    assert 'A2="한국,제품" | B2="1250" | C2="첫째 줄\\n둘째 줄"' in result
    assert 'B3="=SUM(B2:B2)"' in result
    assert 'C3="따옴표 \\"값\\""' in result


def test_tsv_preserves_empty_cells_and_wide_coordinates(tmp_path):
    path = tmp_path / "document"
    path.write_text("\t".join(["한국", ""] + [str(n) for n in range(25)]) + "\n", encoding="utf-8")
    result = text_document(path, "text/tab-separated-values")
    assert 'B1=""' in result
    assert 'AA1="24"' in result


def test_malformed_csv_returns_actionable_error(tmp_path):
    path = tmp_path / "document"
    path.write_text('header\n"unterminated')
    with pytest.raises(ValueError, match="TEXT_DOCUMENT_INVALID"):
        text_document(path, "text/csv")


@pytest.mark.parametrize("mime", ["text/html", "application/xhtml+xml"])
def test_html_preserves_headings_tables_and_inert_form_text(tmp_path, mime):
    path = tmp_path / "document"
    path.write_text('''<!doctype html><html><head><title>숨길 제목</title>
      <script>fetch('https://example.invalid')</script></head><body>
      <h1>사업 보고서</h1><p>첫 <strong>문단</strong>입니다 &amp; 안전합니다.</p>
      <table><tr><th>부서</th><th>매출</th></tr>
      <tr><td rowspan="2">한국</td><td>300원</td></tr><tr><td>400원</td></tr></table>
      <textarea>텍스트 상자</textarea><input value="저장된 답변"/>
      <p>마지막 사실</p><img src="file:///etc/passwd" alt="조직도 설명"/>
      <img src="https://example.invalid/tracker"/>
      </body></html>''', encoding="utf-8")
    result = text_document(path, mime)
    assert "# 사업 보고서" in result
    assert "첫 문단입니다 & 안전합니다." in result
    assert "[행 1] [열 1] 부서 | [열 2] 매출" in result
    assert "[행 2] [열 1, 행 병합 2] 한국 | [열 2] 300원" in result
    assert result.index("300원") < result.index("400원") < result.index("마지막 사실")
    assert "텍스트 상자" in result and "저장된 답변" in result
    assert "[이미지 대체 텍스트: 조직도 설명]" in result
    assert "[이미지: 내용 추출 제외]" in result
    assert "fetch" not in result and "숨길 제목" not in result
    assert "file:" not in result and "example.invalid" not in result


def test_html_removes_active_hidden_content_and_never_resolves_entities(tmp_path):
    path = tmp_path / "document"
    path.write_text('''<!DOCTYPE html [<!ENTITY stolen SYSTEM "file:///etc/passwd">]>
      <p>정상 내용</p><script>alert("SCRIPT_SECRET")</script>
      <style>.STYLE_SECRET{}</style><template>TEMPLATE_SECRET</template>
      <iframe src="https://example.invalid">IFRAME_SECRET</iframe>
      <object>OBJECT_SECRET</object><div hidden><span>HIDDEN_SECRET</span></div>
      <div style="display: none">CSS_SECRET</div><div aria-hidden="true">ARIA_SECRET</div>
      <input type="password" value="PASSWORD_SECRET"><input type="hidden" value="INPUT_SECRET">
      <p>&stolen; 마지막</p>''', encoding="utf-8")
    result = text_document(path, "text/html")
    assert "정상 내용" in result and "마지막" in result
    assert "SECRET" not in result
    assert "root:" not in result


@pytest.mark.parametrize("mime,value", [("text/plain", "가" * 500), ("text/markdown", "나" * 500),
                                      ("text/csv", '"' + "다" * 500 + '"'),
                                      ("text/html", "<p>" + "라" * 500 + "</p>")])
def test_output_retains_exactly_one_extra_character_for_truncation(tmp_path, monkeypatch, mime, value):
    monkeypatch.setattr(text_documents, "MAX_TEXT", 100)
    path = tmp_path / "document"
    path.write_text(value)
    result = text_document(path, mime)
    assert len(result) == 101


@pytest.mark.parametrize("mime,value", [("text/plain", ""), ("text/markdown", ""),
                                      ("text/csv", "\n"),
                                      ("text/html", "<html><body><p></p><script>x</script></body></html>")])
def test_empty_document_has_no_generated_content(tmp_path, mime, value):
    path = tmp_path / "document"
    path.write_text(value)
    assert text_document(path, mime) == ""


def test_input_and_html_depth_limits(tmp_path, monkeypatch):
    path = tmp_path / "document"
    path.write_bytes(b"a" * 101)
    monkeypatch.setattr(text_documents, "MAX_DOCUMENT_BYTES", 100)
    with pytest.raises(ValueError, match="FILE_TOO_LARGE"):
        text_document(path, "text/plain")
    monkeypatch.setattr(text_documents, "MAX_DOCUMENT_BYTES", 10000)
    path.write_text("<div>" * 257 + "deep content" + "</div>" * 257)
    with pytest.raises(ValueError, match="TEXT_DOCUMENT_LIMIT"):
        text_document(path, "text/html")
