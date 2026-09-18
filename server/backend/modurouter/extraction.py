"""Shared bounded extraction subprocess for uploads and fetched documents."""

import asyncio
import json
import os
import signal
import sys
from pathlib import Path

_slots = asyncio.Semaphore(2)


async def extract_file(path: Path, mime: str) -> dict:
    # API runs share this limit, so multiple users cannot each spawn two OCR jobs.
    async with _slots:
        return await _extract_file(path, mime)


async def _extract_file(path: Path, mime: str) -> dict:
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "modurouter.extract", str(path), mime,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
        env={k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL", "TESSDATA_PREFIX", "PYTHONPATH"}},
    )

    async def stop():
        try:
            if getattr(process, "pid", None):
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass
        await process.wait()

    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=75)
        result = json.loads(stdout) if process.returncode == 0 else {"error": "EXTRACTION_FAILED"}
        if not isinstance(result, dict) or not (isinstance(result.get("text"), str) or isinstance(result.get("error"), str)):
            return {"error": "EXTRACTION_FAILED"}
        return result
    except TimeoutError:
        await stop()
        return {"error": "EXTRACTION_TIMEOUT"}
    except asyncio.CancelledError:
        await stop()
        raise
    except (ValueError, UnicodeError):
        return {"error": "EXTRACTION_FAILED"}
