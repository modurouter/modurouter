import asyncio
from datetime import timedelta

from modurouter import files, worker
from modurouter.db import utcnow
from modurouter.models import Attachment, User
from sqlalchemy import select


async def attachment(database, tmp_path, expired=False):
    async with database.begin() as db:
        user = User(google_sub='worker-test', email='worker@example.test', display_name='작업 테스트')
        db.add(user)
        await db.flush()
        row = Attachment(user_id=user.id, filename='document.txt', storage_key=user.id+'/document',
            mime_type='text/plain', size_bytes=7, extraction_status='ready', extracted_text='private',
            expires_at=utcnow()+timedelta(hours=-1 if expired else 1))
        db.add(row)
        await db.flush()
        key, identifier = row.storage_key, row.id
    path = tmp_path/key
    path.parent.mkdir(parents=True)
    path.write_text('private')
    return identifier,path


async def test_expiry_erases_text_and_original(database, monkeypatch, tmp_path):
    monkeypatch.setattr(worker,'Session',database)
    monkeypatch.setattr(files.settings,'upload_directory',tmp_path)
    identifier,path = await attachment(database,tmp_path,expired=True)
    await worker.expire_files()
    async with database() as db:
        row=await db.get(Attachment,identifier)
        assert row.extraction_status=='expired' and row.extracted_text is None
    task=asyncio.create_task(worker.jobs())
    try:
        async with asyncio.timeout(3):
            while path.exists():  # noqa: ASYNC110 - filesystem deletion has no event source
                await asyncio.sleep(.02)
    finally:
        task.cancel()
        await asyncio.gather(task,return_exceptions=True)
    assert not path.exists()


async def test_extraction_timeout_kills_child_and_reports_retryable(database,monkeypatch,tmp_path):
    monkeypatch.setattr(worker,'Session',database)
    monkeypatch.setattr(files.settings,'upload_directory',tmp_path)
    identifier,_=await attachment(database,tmp_path)
    class Child:
        killed=False
        async def communicate(self):raise TimeoutError
        def kill(self):self.killed=True
        async def wait(self):return -9
    child=Child()
    async def spawn(*args,**kwargs):return child
    monkeypatch.setattr(worker.asyncio,'create_subprocess_exec',spawn)
    await worker.process_extraction(identifier)
    assert child.killed
    async with database() as db:
        row=await db.scalar(select(Attachment).where(Attachment.id==identifier))
        assert row.extraction_status=='failed' and row.error_code=='EXTRACTION_TIMEOUT' and row.retryable


async def test_extraction_cancellation_reaps_child(database, monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "Session", database)
    monkeypatch.setattr(files.settings, "upload_directory", tmp_path)
    identifier, _ = await attachment(database, tmp_path)
    started = asyncio.Event()

    class Child:
        returncode = None
        killed = False
        reaped = False

        async def communicate(self):
            started.set()
            await asyncio.Event().wait()

        def kill(self):
            self.killed = True

        async def wait(self):
            self.reaped = True

    child = Child()

    async def spawn(*args, **kwargs):
        return child

    monkeypatch.setattr(worker.asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(worker.process_extraction(identifier))
    await asyncio.wait_for(started.wait(), 3)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert child.killed and child.reaped


async def test_deletion_wins_over_inflight_extraction(database, monkeypatch, tmp_path):
    monkeypatch.setattr(worker, "Session", database)
    monkeypatch.setattr(files.settings, "upload_directory", tmp_path)
    identifier, _ = await attachment(database, tmp_path)
    started, finish = asyncio.Event(), asyncio.Event()

    class Child:
        returncode = 0

        async def communicate(self):
            started.set()
            await finish.wait()
            return b'{"text":"must not reappear"}', b""

    async def spawn(*args, **kwargs):
        return Child()

    monkeypatch.setattr(worker.asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(worker.process_extraction(identifier))
    await asyncio.wait_for(started.wait(), 3)
    async with database.begin() as db:
        row = await db.get(Attachment, identifier)
        row.extracted_text = None
        row.extraction_status = "expired"
        await db.flush()
        finish.set()
        await asyncio.sleep(0.1)
    await asyncio.wait_for(task, 3)
    async with database() as db:
        row = await db.get(Attachment, identifier)
        assert row.extraction_status == "expired" and row.extracted_text is None
