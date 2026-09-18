# Models and speech API release — 2026-09-18

User approved production deployment, migration 0006, and API/worker restart.

- Deployed main.py, harness.py, providers.py, models.py, model_options.py, run_input.py, speech.py and migration 0006.
- Preserved existing production environment, provider keys, model allowlist, and spending limits.
- Alembic reports `0006 (head)`.
- API container healthy; worker running; public readiness returns ready.
- Production and local frontend proxy return the same three models: qwen/qwen3-30b-a3b-instruct-2507, openai/gpt-4o-mini, upstage/solar-pro-3.
- All three currently expose empty effort capabilities. Frontend disables effort selection for this catalog, including automatic routing.
- STT key configuration present (value never printed). Physical microphone/provider transcription was not exercised.
- Browser verified model list and selection. No paid chat or audio request was sent.
- Frontend tests: 15 passed. Selected server tests: 33 passed. Typecheck and lint passed.
- Prior image: `modurouter-api:before-model-speech-1789700847`.
- Prior source: `/opt/modurouter/before-model-speech-1789700847-source.tar.gz`.

Rollback of application image can leave the additive speech_requests table in place. Do not downgrade/delete it automatically. This release updated the API; the redesigned frontend remains the local client at localhost:3107. No Git commit or push performed.

## 10-minute recording follow-up

- Kept `gpt-4o-mini-transcribe`; raised the validated recording limit to 600 seconds.
- Server processes consecutive 120-second WAV parts and joins the results, under one budget reservation and daily request count.
- Deployed speech.py and Caddy upload/timeouts. Caddy configuration validated and reloaded; API and worker restarted.
- Verified running API constants: `gpt-4o-mini-transcribe 600 19200044 120`; API healthy and internal readiness ready. The immediate post-restart import check exited before readiness; a subsequent check succeeded.
- Rollback image/source prefix: `before-speech-10min-1789701385`.
- STT tests: 14 passed; frontend tests: 15 passed; production frontend build passed. Browser shows the 10-minute tooltip after refresh.
- No physical microphone recording or paid OpenAI transcription was performed.

## Follow-up verification and redeploy

A later live check found `/v1/models` returned 404 even though containers were recent and the database was at 0006. Remote `backend/modurouter/main.py` contained only the old `/v1/models/status` route. Prior notes alone were not sufficient evidence of the running source.

Redeployed the current local backend, rebuilt the image, reran Alembic, recreated API/worker, and reloaded Caddy while preserving the production `.env` and spending limits. Rollback image: `modurouter-api:before-settings-fix-1789701375`; matching source archive is in `/opt/modurouter/`.

After this redeploy, both the public API and localhost:3107 proxy returned all three configured models; `/v1/config` returned `stt_available: true`; `/health/ready` returned ready. Browser verification displayed the three model choices without the update-required error. Current model capabilities still have empty effort lists. Paid transcription and chat generation were not invoked. Selected server tests: 35 passed; frontend tests: 15 passed; lint and typecheck passed.
