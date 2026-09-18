import asyncio
import json
import signal
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from modurouter import extraction


@pytest.mark.parametrize('response,expected', [
    ({'text': '추출된 문서', 'truncated': False}, {'text': '추출된 문서', 'truncated': False}),
    ({'error': 'OFFICE_INVALID'}, {'error': 'OFFICE_INVALID'}),
    ([], {'error': 'EXTRACTION_FAILED'}),
    ({'text': 123}, {'error': 'EXTRACTION_FAILED'}),
])
async def test_extraction_result_validation(monkeypatch, response, expected):
    process = AsyncMock()
    process.returncode = 0
    process.communicate.return_value = (json.dumps(response).encode(), b'')
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(extraction.asyncio, 'create_subprocess_exec', spawn)
    monkeypatch.setenv('SECRET_TEST_KEY', 'must-not-propagate')
    assert await extraction.extract_file(Path('/tmp/storage-key'), 'application/pdf') == expected
    assert spawn.call_args.kwargs['start_new_session'] is True
    assert 'SECRET_TEST_KEY' not in spawn.call_args.kwargs['env']


@pytest.mark.parametrize('cancelled', [False, True])
async def test_timeout_and_cancellation_kill_entire_process_group(monkeypatch, cancelled):
    process = AsyncMock()
    process.pid = 12345
    process.communicate.side_effect = asyncio.CancelledError if cancelled else TimeoutError
    spawn = AsyncMock(return_value=process)
    calls = []
    monkeypatch.setattr(extraction.asyncio, 'create_subprocess_exec', spawn)
    monkeypatch.setattr(extraction.os, 'killpg', lambda pid, sig: calls.append((pid, sig)))
    if cancelled:
        with pytest.raises(asyncio.CancelledError):
            await extraction.extract_file(Path('/tmp/storage-key'), 'application/pdf')
    else:
        assert await extraction.extract_file(Path('/tmp/storage-key'), 'application/pdf') == {'error': 'EXTRACTION_TIMEOUT'}
    assert calls == [(12345, signal.SIGKILL)]
    process.wait.assert_awaited_once()


async def test_actual_subprocess_extracts_extensionless_document(tmp_path):
    path = tmp_path / 'storage-key'
    path.write_text('문서 추출기를 실제 하위 프로세스로 확인합니다.', encoding='utf-8')
    result = await extraction.extract_file(path, 'text/plain')
    assert result == {'text': path.read_text(), 'truncated': False}


async def test_concurrent_runs_share_extraction_capacity(tmp_path, monkeypatch):
    running = peak = 0
    monkeypatch.setattr(extraction, '_slots', asyncio.Semaphore(2))

    async def extract_one(path, mime):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        try:
            await asyncio.sleep(0.01)
            return {'text': path.name}
        finally:
            running -= 1

    monkeypatch.setattr(extraction, '_extract_file', extract_one)
    results = await asyncio.gather(*(extraction.extract_file(tmp_path / str(i), 'application/pdf') for i in range(5)))
    assert peak == 2 and running == 0 and len(results) == 5


async def test_cancelled_extraction_stops_real_child_process(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys

    original_spawn = asyncio.create_subprocess_exec
    processes = []
    pidfile = tmp_path / 'child.pid'
    script = (
        'import pathlib, subprocess, sys, time; '
        'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"]); '
        'pathlib.Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(300)'
    )

    async def spawn(*args, **kwargs):
        process = await original_spawn(sys.executable, '-c', script, str(pidfile), **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(extraction.asyncio, 'create_subprocess_exec', spawn)
    task = asyncio.create_task(extraction.extract_file(tmp_path / 'document', 'text/plain'))
    try:
        async with asyncio.timeout(5):
            while not pidfile.exists():  # noqa: ASYNC110 - filesystem signal from a child process
                await asyncio.sleep(0.01)
        child_pid = int(pidfile.read_text())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert processes[0].returncode == -signal.SIGKILL
        async with asyncio.timeout(5):
            while True:
                status = await asyncio.to_thread(subprocess.run, ['ps', '-o', 'stat=', '-p', str(child_pid)],
                                                 capture_output=True, text=True, check=False)
                state = status.stdout.strip()
                if not state or state.startswith('Z'):
                    break
                await asyncio.sleep(0.01)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        for process in processes:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
