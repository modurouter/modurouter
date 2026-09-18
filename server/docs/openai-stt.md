# OpenAI speech input

Frontend dictation uses `gpt-4o-mini-transcribe` through the existing authenticated backend. It does not use browser speech recognition. The browser records at most 10 minutes with MediaRecorder, then converts to mono PCM16 16kHz WAV. The backend independently validates format, actual frame data, duration and byte size before sending the audio to OpenAI's `/v1/audio/transcriptions` endpoint with `language=ko`. The API key stays in the server's existing `OPENAI_API_KEY` setting.

The returned text is inserted into the composer; it is not automatically submitted to chat. Closing the voice panel cancels a pending recording/upload. Audio is not saved to disk or the database. Browser permission denial, unsupported recording, missing server setup, provider failure and empty transcripts receive UI messages.

Long recordings are split into consecutive 120-second WAV parts on the server and their transcripts are joined. The full recording consumes one daily request allowance. Parts have no overlap; a word spanning a part boundary can affect recognition. The full operation has a 300-second processing timeout, with 330-second proxy timeouts. The speech route accepts up to 21 MB at the edge; format-specific validation limits PCM audio to 600 seconds (19,200,044 bytes).

## Release requirements

- Apply migrations through `0008` (speech remains `0006`, routing is `0007`, runtime settings are `0008`) using the existing release process (`uv run alembic upgrade head` from `server/`).
- Deploy the updated API and frontend together. The old API does not have the transcription endpoint; the frontend checks `stt_available` in `/v1/config` before requesting microphone access.
- Set the existing server `OPENAI_API_KEY`. No new key belongs in the browser or any `NEXT_PUBLIC_*` variable.
- Production release status is recorded in `deployment-2026-09-18-models-speech.md`. See the integration release record for live transcription verification.

## Cost boundaries

Official estimated cost is $0.003/minute; actual cost is token based. Sources reviewed on 2026-09-18:

- https://developers.openai.com/api/docs/models/gpt-4o-mini-transcribe
- https://developers.openai.com/api/docs/pricing
- https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create

Each STT request consumes one existing daily request allowance and participates in the user and shared guest dollar budget. A $0.03 hold is reserved before the call, then replaced with the cost calculated from returned usage. This hold is not the expected price. An ambiguous network interruption or missing usage keeps the reservation pending; it is never silently treated as free or automatically resent. `speech_requests` records reservation status without storing audio or transcript. Pending STT holds require operator review; the existing chat generation reconciliation worker does not reconcile them. Above-reservation cost blocks further paid requests as it does for chat.

## Verification

`server/.venv/bin/pytest -q server/tests/test_speech.py` from the repository root verifies WAV limits, token accounting, successful transcription, rejected requests, uncertain charges, shared guest limits and budget rejection against an isolated in-memory SQLite database and HTTP mock. It does not access production or incur API costs. Typecheck runs from `client/`.

STT reads the same effective runtime policy as chat, including provider activation and guest/member/admin request limits. Administrator request counts are unlimited; monetary budgets still apply. Korean answer playback uses the device browser speech synthesis with explicit Korean voice selection.
