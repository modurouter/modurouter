"""Original Korean documents saved by LibreOffice; the same fixtures run in Linux CI."""
import json
import shutil
import sys
from pathlib import Path

import pytest
from modurouter.document_formats import FORMATS
from modurouter.extract import extract

FIXTURES = Path(__file__).parent / 'fixtures/documents'
CASES = {
    'korean-report.docx': ['가람101', '나래202', '라온404', '1250000', '바람606', '다솜303', '마루505'],
    'korean-budget.xlsx': ['가람101', '나래202', '라온404', '배송현황', '사과707', '3600', 'B2*C2'],
    'korean-slides.pptx': ['가람101', '나래202', '라온404', '전환율', '27%', '92점', '청록호', '바람606'],
    'korean-report.doc': ['가람101', '나래202', '라온404', '1250000', '바람606', '다솜303'],
    'korean-report.odt': ['가람101', '나래202', '라온404', '1250000', '바람606', '다솜303'],
    'korean-report.rtf': ['가람101', '나래202', '라온404', '1250000', '바람606'],
    'korean-budget.xls': ['가람101', '나래202', '라온404', '배송현황', '사과707', '3600'],
    'korean-slides.ppt': ['가람101', '나래202', '라온404', '전환율', '27%', '92점', '바람606'],
    'korean-notes.md': ['가람101', '나래202', '라온404'],
    'korean-page.html': ['가람101', '나래202', '라온404', '5,000원'],
    'korean-data.csv': ['가람101', '나래202', '라온404', '둘째 줄'],
    'korean-data.tsv': ['가람101', '나래202', '라온404', '둘째 줄'],
    'korean-cp949.csv': ['가람101', '나래202', '라온404', '한글 인코딩 검증'],
}


@pytest.mark.parametrize('name,facts', CASES.items())
def test_native_document_content_and_order(name, facts):
    path = FIXTURES / name
    if path.suffix in {'.doc', '.xls', '.ppt', '.odt', '.rtf'} and (
            sys.platform != 'linux' or not shutil.which('libreoffice')):
        pytest.skip('Legacy conversion is tested inside the Linux deployment image')
    result = extract(path, FORMATS[path.suffix])
    assert not result['truncated']
    for fact in facts:
        assert fact in result['text'], (name, fact)
    positions = [result['text'].index(fact) for fact in ('가람101', '나래202', '라온404')]
    assert positions == sorted(positions)
    if path.suffix == '.html':
        assert 'SCRIPT_MUST_NOT_LEAK' not in result['text']
        assert 'STYLE_MUST_NOT_LEAK' not in result['text']


def test_native_facts_reach_model_context():
    from modurouter.harness import build_context

    for name in ['korean-report.docx', 'korean-budget.xlsx', 'korean-slides.pptx']:
        result = extract(FIXTURES / name, FORMATS[Path(name).suffix])
        source = {'source_id': 'S1', 'scope': 'attachment', 'title': name, **result}
        messages, partial = build_context([], '처음 중간 끝과 표 및 각주와 발표자 노트의 코드를 알려줘', [source], False, 16000)
        payloads = [json.loads(message['content']) for message in messages if message['content'].startswith('{')]
        text = '\n'.join(item.get('text', '') for item in payloads)
        for fact in CASES[name]:
            assert fact in text, (name, fact)
        assert not partial


def test_extraction_limitations_survive_question_aware_excerpt():
    from modurouter.context import build_context

    notice = "이미지와 차트의 시각 정보는 포함하지 않습니다."
    source = {"source_id": "S1", "scope": "attachment", "title": "예산.xlsx",
              "text": "설명 " * 20000 + "최종코드는 가람101", "limitations": [notice]}
    messages, truncated = build_context([], "최종코드는?", [source], False, 3000)
    content = "\n".join(message["content"] for message in messages)
    assert truncated and notice in content and "가람101" in content
