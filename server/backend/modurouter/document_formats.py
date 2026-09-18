"""Shared upload and public-document format registry."""

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
OFFICE_PARTS = {
    DOCX: ("word/document.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"),
    XLSX: ("xl/workbook.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"),
    PPTX: ("ppt/presentation.xml", "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"),
}
TEXT_FORMATS = {".txt": "text/plain", ".md": "text/markdown", ".markdown": "text/markdown",
                ".csv": "text/csv", ".tsv": "text/tab-separated-values", ".html": "text/html",
                ".htm": "text/html", ".json": "text/plain", ".xml": "text/plain"}
TEXT_EXTENSIONS = set(TEXT_FORMATS)
LEGACY_FORMATS = {".doc": "application/msword", ".xls": "application/vnd.ms-excel",
                  ".ppt": "application/vnd.ms-powerpoint", ".odt": "application/vnd.oasis.opendocument.text",
                  ".rtf": "application/rtf"}
FORMATS = {**TEXT_FORMATS, **LEGACY_FORMATS,
           ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
           ".hwp": "application/x-hwp", ".hwpx": "application/hwp+zip",
           ".docx": DOCX, ".xlsx": XLSX, ".pptx": PPTX}
DOCUMENT_MIMES = set(FORMATS.values()) - set(TEXT_FORMATS.values())
TEXT_MIMES = {"application/json", "application/xml", "application/javascript", "application/x-ndjson"}
MAX_TEXT = 80000
MAX_DOCUMENT_BYTES = 10 * 1024**2



def extraction_notes(mime: str) -> list[str]:
    if mime in OFFICE_PARTS or mime in LEGACY_FORMATS.values() or mime in {"application/x-hwp", "application/hwp+zip"}:
        notes = ["본문과 표의 텍스트를 읽습니다. 원본 배치와 포함된 이미지 및 차트의 시각 정보는 재현하지 않습니다."]
        if mime in {XLSX, "application/vnd.ms-excel"}:
            notes.append("셀 좌표와 저장 값, 수식, 표시 형식을 제공합니다. 저장된 수식 결과가 없으면 계산값을 확인할 수 없습니다.")
        if mime == "application/vnd.ms-excel":
            notes.append("XLS 수식 결과는 변환 시점 값이며 원본에 저장된 값과 다를 수 있습니다.")
        if mime in LEGACY_FORMATS.values():
            notes.append("호환 형식으로 변환해 읽으므로 일부 개체와 배치가 달라질 수 있습니다.")
        return notes
    if mime in {"text/html", "application/xhtml+xml"}:
        return ["HTML에 저장된 텍스트와 표를 읽습니다. 스크립트와 외부 페이지를 실행하지 않으며 이미지는 대체 텍스트만 읽습니다."]
    return []
