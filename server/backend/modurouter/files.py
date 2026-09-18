import asyncio
from datetime import timedelta
from pathlib import Path

import magic
from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import current_user
from .billing import admission_lock
from .config import get_settings
from .conversations import owned_conversation
from .db import get_db, new_id, utcnow
from .document_formats import (
    FORMATS,
    LEGACY_FORMATS,
    OFFICE_PARTS,
    TEXT_EXTENSIONS,
    TEXT_MIMES,
    extraction_notes,
)
from .errors import AppError
from .hangul import validate_container
from .legacy_office import validate_legacy
from .models import Attachment, Job, User
from .office import validate_office

router = APIRouter(prefix="/v1/attachments")
settings = get_settings()
ALLOWED = FORMATS
HANGUL_UPLOAD_ERRORS = {
    "HWP_INVALID": "한글 문서가 손상되었습니다. 한글에서 다시 저장한 파일을 첨부해 주세요.",
    "HWP_ENCRYPTED": "암호를 해제한 한글 문서를 다시 첨부해 주세요.",
    "HWP_VERSION_UNSUPPORTED": "이 버전의 한글 문서는 HWPX로 다시 저장한 뒤 첨부해 주세요.",
    "HWP_SIZE_LIMIT": "한글 문서의 내부 데이터가 너무 큽니다. 파일을 나누어 첨부해 주세요.",
}


def storage_path(key: str) -> Path:
    base = settings.upload_directory.resolve()
    path = (base / key).resolve()
    if not path.is_relative_to(base) or path == base:
        raise ValueError("Invalid storage key")
    return path


async def owned_attachment(db: AsyncSession, user_id: str, identifier: str) -> Attachment:
    row = await db.scalar(select(Attachment).where(Attachment.id == identifier, Attachment.user_id == user_id))
    if row is None:
        raise AppError("NOT_FOUND", "첨부파일을 찾을 수 없습니다.", 404)
    return row


def attachment_view(row: Attachment):
    expired = row.expires_at <= utcnow() or row.extraction_status == "expired"
    return {"id": row.id, "attachment_id": row.id, "filename": row.filename,
            "status": "expired" if expired else row.extraction_status,
            "preview": None if expired else row.extracted_text, "truncated": row.truncated,
            "error_code": row.error_code, "retryable": row.retryable,
            "extraction_notes": extraction_notes(row.mime_type),
            "expires_at": row.expires_at.isoformat() + "Z"}


@router.post("")
async def upload(file: UploadFile = File(...), conversation_id: str = Form(...),
                 user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    await db.commit()
    await admission_lock(db)
    await owned_conversation(db, user.id, conversation_id)
    # Serialize upload admission to prevent concurrent requests bypassing the storage limit.
    count = await db.scalar(select(func.count()).select_from(Attachment).where(
        Attachment.user_id == user.id, Attachment.expires_at > utcnow(), Attachment.extraction_status != "expired"))
    if count >= 30:
        raise AppError("UPLOAD_LIMIT", "보관 중인 첨부파일을 삭제한 뒤 다시 시도해 주세요.", 429)
    filename = Path(file.filename or "").name[:255]
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED:
        raise AppError("FILE_UNSUPPORTED", "PDF, 한글, Office 문서와 텍스트 파일 또는 PNG/JPG 이미지를 첨부해 주세요.")
    identifier = new_id()
    key = f"{user.id}/{identifier}"
    path = storage_path(key)
    row = Attachment(id=identifier, user_id=user.id, conversation_id=conversation_id, filename=filename,
        storage_key=key, mime_type=ALLOWED[extension], size_bytes=0, extraction_status="uploading",
        expires_at=utcnow() + timedelta(hours=settings.attachment_ttl_hours))
    db.add(row)
    await db.commit()
    size = 0
    try:
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True, mode=0o700)
        handle = await asyncio.to_thread(path.open, "xb")
        try:
            await asyncio.to_thread(path.chmod, 0o600)
            while chunk := await file.read(65536):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise AppError("FILE_TOO_LARGE", f"파일은 {settings.max_upload_bytes / (1024 * 1024):g}MB까지 첨부할 수 있습니다.", 413)
                await asyncio.to_thread(handle.write, chunk)
        finally:
            await asyncio.to_thread(handle.close)
            await file.close()
        if extension in LEGACY_FORMATS:
            mime = ALLOWED[extension]
            try:
                await asyncio.to_thread(validate_legacy, path, mime)
            except ValueError as exc:
                raise AppError(str(exc), "문서가 손상되었거나 암호화되어 있습니다. 암호를 해제하고 원래 프로그램에서 다시 저장해 첨부해 주세요.") from exc
        elif ALLOWED[extension] in OFFICE_PARTS:
            mime = ALLOWED[extension]
            try:
                await asyncio.to_thread(validate_office, path, mime)
            except ValueError as exc:
                raise AppError(str(exc), "Office 문서 형식을 확인해 주세요. 암호화된 파일은 암호를 해제한 뒤 첨부해 주세요.") from exc
        elif extension in (".hwp", ".hwpx"):
            mime = ALLOWED[extension]
            try:
                await asyncio.to_thread(validate_container, path, mime)
            except ValueError as exc:
                code = str(exc)
                raise AppError(code, HANGUL_UPLOAD_ERRORS.get(code,
                    "파일의 실제 형식과 확장자가 일치하지 않습니다.")) from exc
        else:
            mime = await asyncio.to_thread(magic.from_file, str(path), mime=True)
        # libmagic classifies valid text by syntax (JSON, HTML, XML, etc.).
        # Keep it inert plain text; the extractor still rejects binary/encoding errors.
        if extension in TEXT_EXTENSIONS and (mime.startswith("text/") or mime in TEXT_MIMES):
            mime = ALLOWED[extension]
        if size == 0 or mime != ALLOWED[extension]:
            raise AppError("FILE_TYPE_MISMATCH", "파일의 실제 형식과 확장자가 일치하지 않습니다.")
        await admission_lock(db)
        await owned_conversation(db, user.id, conversation_id)
        await db.refresh(row)
        if row.extraction_status == "expired":
            raise AppError("ATTACHMENT_EXPIRED", "삭제한 첨부파일입니다.")
        row.size_bytes = size
        row.mime_type = mime
        row.extraction_status = "queued"
        db.add(Job(type="extract", payload={"attachment_id": identifier}))
        await db.commit()
        return attachment_view(row)
    except BaseException:
        await asyncio.to_thread(path.unlink, missing_ok=True)
        await db.rollback()
        failed = await db.get(Attachment, identifier)
        if failed:
            failed.extracted_text = None
            failed.extraction_status = "failed"
            failed.error_code = "UPLOAD_FAILED"
            failed.expires_at = utcnow()
            await db.commit()
        raise


@router.get("/{identifier}")
async def status(identifier: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return attachment_view(await owned_attachment(db, user.id, identifier))


@router.delete("/{identifier}")
async def remove(identifier: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    row = await owned_attachment(db, user.id, identifier)
    row.extracted_text = None
    row.extraction_status = "expired"
    row.expires_at = utcnow()
    db.add(Job(type="delete_file", payload={"storage_key": row.storage_key}))
    await db.commit()
    return {"deleted": True}
