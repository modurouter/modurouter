# Modurouter

Korean AI harness: FastAPI, MariaDB, OpenRouter, ZenMux, OpenAI, Upstage and Next.js.

The prototype is deployed at https://modurouter.today. Visitors can use the service immediately without signing in, or optionally sign in with Google. The `/admin` page accepts the server-configured username and password and opens the routing administration panel. The home page automatically creates a private guest session through `/auth/guest` when no valid session exists. Guest cookies are session-only. Guests can ask questions and attach files, and share the configured daily request and cost limits. Guest conversations stay separate from signed-in accounts and are not transferred on login. Native browser Korean voice input and readout have been tested; physical microphone and speaker quality were not measured. The acceptance checklist and explicit scope decisions are in [docs/phase-1.md](docs/phase-1.md).
The selected `modurouter.today` deployment uses a same-origin Vercel proxy for auth and API requests to `api.modurouter.today`.

## Local backend

Install Python 3.12 and uv. Install MariaDB, libmagic, Tesseract and its Korean and English language data. Root `.env` is the only manually maintained configuration file and must have mode 600. No example environment file is provided.

```sh
cd server
uv sync --frozen
uv run alembic upgrade head
uv run uvicorn modurouter.main:app --reload --port 8000
```

Run the worker separately:

```sh
uv run python -m modurouter.worker
```

The API never creates tables at startup. Run Alembic migrations explicitly. Missing budget configuration defaults to zero paid spending; missing automatic model allowlists stop automatic model calls. Google login reports an unavailable state when credentials are absent.

## Login configuration

Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in root `.env` using a Google Cloud OAuth client of type Web application. Register `https://modurouter.today/auth/google/callback` and `http://localhost:3000/auth/google/callback` as authorized redirect URIs for the current deployment and local development. A different API origin requires its own exact `/auth/google/callback` URI. Only `openid email profile` scopes are requested.

Set `ADMIN_USERNAME` and `ADMIN_PASSWORD` in root `.env`. These credentials are checked only by the backend and never embedded in the frontend. Both login methods issue the same persistent HttpOnly session and CSRF protection, with the same member features. Administrator accounts have no daily request-count limit; daily cost limits still apply. Invalid password login attempts are limited to 10 per five-minute window per server-resolved client address across API workers. Raw forwarding headers are not trusted by this endpoint. The unpublished API port trusts its internal proxy; Caddy replaces forwarded addresses with the ingress peer. Users behind the same NAT or Vercel egress address share a limit, but other addresses remain usable. Run migration `0004` before using password login. The deployment script selects these settings from root `.env` for the application containers.

## Tests

The MariaDB user configured in `.env` needs access to a separate `modurouter_test` schema. Tests reset that schema only.

```sh
uv run ruff check backend tests scripts
uv run pytest -q
```

## Model providers

Nonempty `OPENROUTER_API_KEY`, `ZENMUX_API_KEY`, `OPENAI_API_KEY` and `UPSTAGE_API_KEY`
in root `.env` enable the corresponding adapters. ZenMux must use a PAYG key.
Model IDs in `MODEL_ALLOWLIST` and `TOOL_MODEL_ALLOWLIST` are canonical names such
as `openai/gpt-4o-mini` or `upstage/solar-pro-3`. A bare canonical name permits any
configured provider that offers it. Use `zenmux::openai/gpt-4o-mini` to permit only
one route. Empty automatic allowlists disable automatic routing. Explicit free and manual selection use the priced text catalog, subject to the administrator's separate selectable-model list. Credentials for one
provider are never sent to another provider or to the browser.

Automatic routing compares eligible routes across enabled providers, within the existing
price caps and user budgets. Each provider has its own atomic catalog refresh and
freshness state. An unavailable or stale provider does not disable healthy routes.
The single fallback prefers a different provider; partial answers are never retried.
Account errors can fall back to a different provider, but not another model on the
same account. Reservations, generation IDs and reconciliation are provider-scoped.

OpenRouter and ZenMux catalogs refresh every ten minutes by default. ZenMux uses
`pricings` arrays with explicit units and conditional tiers; reservations use the
highest tier. OpenRouter supports an upstream maximum-price constraint. ZenMux uses
price-priority routing but does not expose that same constraint, so catalog caps are
checked locally and an actual billing overrun blocks further paid calls for that user.
Neither missing prices nor unsupported billing dimensions are treated as free.

OpenAI and Upstage model-list APIs return availability, not prices. Their reviewed
text-model tariffs live in `backend/modurouter/direct_catalog.py`, with official
source URLs, a review date and an expiry date. They are **reference prices**, not
live pricing feeds. Review and update them before expiry; expired references cannot
route. Direct support currently covers GPT-4o mini, GPT-4.1 nano, GPT-5 nano, Solar
Pro 3 and Solar Pro 2. Other native models require a reviewed tariff and payload
support before they can become eligible. Tax and prepaid credit bonuses are excluded.

Direct costs are calculated from returned token usage, including cached input discounts
and reasoning tokens. The request's price snapshot and returned usage are persisted
for recovery. The UI distinguishes these calculated costs from provider-reported bills.
If a direct stream is interrupted before usage arrives, its reservation remains pending;
these APIs have no per-request lookup for non-stored chats. ZenMux billing arrives
through `/api/v1/management/generation`, normally after 3-5 minutes, and the worker
reconciles it. Missing billing data never settles as zero.

`GET /v1/models/status` and `python -m modurouter.ops_status` expose freshness per
configured provider. Apply migration `0005` before running the updated API/worker.
Compose and deployment scripts forward all four model keys from the root `.env`.
The quality evaluator accepts `--provider openrouter|zenmux|openai|upstage`.

## User model choice and administration

Apply migrations through `0008` before running this version. The composer offers automatic
cost ordering, free-only routing, and explicit provider/model selection. Free-only requests
never fall back to paid models. Explicit selection does not substitute another model or
provider and is allowed above the automatic price caps. OpenRouter receives the selected
catalog price as its request ceiling. Daily budgets still apply. Tool planning requires a
model on the tool allowlist in every mode. Prices come from the current catalog; a low
price alone is not labeled a discount. The saved run records its requested routing mode
and the provider used for the answer.

`/admin` now provides authenticated routing controls. `GET/POST /v1/admin/settings`
reads or saves the non-secret policy in `runtime_settings`. It covers provider activation,
automatic and tool allowlists, selectable models, the default routing mode and model,
manual-selection availability, budgets, request limits, token limits, execution limits,
and price refresh/freshness intervals. Changes take effect for newly admitted requests;
an in-flight run retains its configuration. The worker reads the stored price refresh
interval. A revision check rejects concurrent stale saves. Existing idempotent requests
retain their original route even when the default changes.

Keys and admin login credentials remain solely in root `.env`. The panel exposes only
whether each provider key exists. Ordinary members and guests cannot access admin APIs.
`GET /v1/admin/models` includes priced models from disabled providers so administrators
can enable them. `POST /v1/admin/models/refresh` refreshes catalogs without a model call.
Before the first save, the non-secret policy falls back to `.env` defaults. Subsequent
admin saves persist across API and worker restarts. A null selectable-model list permits
the whole valid catalog; an empty list permits no free or manual model selections.

## Deployment configuration

`compose.yaml` contains proxy, API, worker and MariaDB services. Database and upload volumes persist across container restarts. The database has no host port. Populate root `.env` with the API TLS hostname and production origin before deployment. `PRODUCTION_WEB_ORIGIN` is `https://modurouter.today` for this deployment. `PRODUCTION_API_ORIGIN` currently matches it, so the browser uses the same-origin proxy. `API_DOMAIN` is `api.modurouter.today`, with an A record pointing to the VPS and TLS managed by Caddy. Vercel proxies browser API and auth requests to this host. `www.modurouter.today` redirects to the apex domain. For an optional direct-API topology, set the API origin to a distinct HTTPS sibling host. The deployment scripts pass the API address from root `.env` into the server and Vercel build. Only when the API origin differs from the web origin do browser requests go directly to the API host, Vercel rewrites get omitted, and the OAuth callback use the API host. Runtime credentials are explicitly selected from `.env`; VPS login and Vercel deployment credentials must never be copied into application containers.

Deployment order: build the release image, start MariaDB, run `alembic upgrade head` through the API image, start API and worker, then proxy. Verify liveness, readiness and the public web flow. Preserve the prior application image for rollback. No database backup or restore job is configured, per the user's explicit instruction.

SSH tooling pins the host key using `VPS_KNOWN_HOSTS` in root `.env` (known_hosts line format) and reads access settings from the same file. Password access was verified. Fail2ban is installed, enabled and active with the SSH jail in `infra/fail2ban.local`; an nftables ban/unban was verified. Only SSH and HTTP/HTTPS are allowed through the host firewall.

## References

- [OpenRouter provider routing](https://openrouter.ai/docs/guides/routing/provider-selection)
- [OpenRouter usage accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting)
- [Next.js rewrites](https://nextjs.org/docs/app/api-reference/config/next-config-js/rewrites)
- [Docker Ubuntu installation](https://docs.docker.com/engine/install/ubuntu/)

## Layout and commands

The root contains only `.env`, `AGENTS.md`, `client/`, `server/`, `.ops/`, `.agents/` and `.gitignore`. Credentials and operations artifacts are ignored. No root package manifest or example environment file is needed.

`.ops/` must contain exactly `deploy.sh` and `run.sh`. Store generated logs, test artifacts and local runtime data in ignored `server/.runtime/` or the system temporary directory. From the root, use `.ops/run.sh api`, `.ops/run.sh worker` and `.ops/run.sh client` in separate terminals. Run `.ops/run.sh migrate` against an already running, configured local MariaDB before starting the API. `.ops/deploy.sh [all|server|client]` invokes the existing deployment scripts and defaults to deploying both services. The scripts read root `.env` without sourcing it.

Start the web application from `client/` with `npm ci` and `npm run dev`. It proxies to port 8000 locally. In the current deployment, Vercel receives `API_UPSTREAM_URL` from root `.env` as a build value and proxies browser requests to the VPS. When `PRODUCTION_API_ORIGIN` differs from `PRODUCTION_WEB_ORIGIN`, the client deployment builds with that public API origin and sends browser requests there directly.

From `server/`, `uv run python scripts/deploy.py` deploys the API stack and preserves `modurouter-api:previous`. `uv run python scripts/deploy_client.py` deploys the web application. Deployment values are derived from root `.env` without sourcing it. App rollback on the VPS is `RELEASE_TAG=previous docker compose up -d --no-build api worker` in `/opt/modurouter`; review migration compatibility first. This does not restore a database.

## Monitoring and limits

Inspect `/health/live` and `/health/ready` on the API HTTPS origin. On the VPS, `docker compose exec -T api python -m modurouter.ops_status` reports aggregate price freshness, platform spending, pending charges and worker queue age without user content. API/worker logs record request and run IDs, terminal status, error code, model, cost and latency, plus worker processing delay. `GET /v1/models/status` reports price freshness and `GET /v1/usage` reports the signed-in user's held reservations. A generation with unknown cost retains its reservation until provider reconciliation succeeds. A request cancelled before OpenRouter returns a generation ID may remain uncorrelatable and keep its reservation for that quota day. When present, the `X-Generation-Id` response header is saved before stream content to improve reconciliation after early cancellation.

Daily question limits reset at Seoul midnight: guests share 30 requests (`GUEST_DAILY_REQUEST_LIMIT`), free members receive 50 requests each (`USER_DAILY_REQUEST_LIMIT`), and administrators have unlimited requests. Daily cost limits still apply to all accounts. Historical guest quota records remain available for outstanding cost reconciliation. It records total platform spending without a platform dollar cap. Per the user's decision, no separate OpenRouter key spending cap is required.

Browser disconnect propagation through Vercel is not guaranteed. The client sends a best-effort cancellation request on page exit; the explicit Stop button calls the same endpoint. Abrupt network loss can leave the upstream running until completion or the 120-second server limit. It is still charged and accounted, and reconnecting never starts a replacement automatically.


## Review fixes and recovery

The landing page advertises configured Google and administrator login methods. Either can be omitted from `.env`; an unconfigured method remains unavailable. Guest access is available even when neither login method is configured. Existing valid sessions are reused, including signed-in accounts.

`MAX_INPUT_TOKENS` defaults to 16384 and is forwarded by deployment. The estimator reserves two tokens per Hangul/CJK character with framing and headroom, rather than counting every UTF-8 byte. It remains an estimate across providers. Model context windows and existing spending limits still apply. Source prefixes use the available input budget, and excluded content is disclosed beside the answer. The extractor retains its 20,000-character and 20-page limits.

Rejected HTTP calls and failures before a connection is established settle at zero. Interrupted streams and ambiguous read/write timeouts retain reservations because provider charges may exist. Historical unknown charges are not retroactively marked free.

After investigating a reservation overrun and verifying the current model prices, an operator can run `uv run python -m modurouter.billing_review USER_ID --reviewed`. Recovery refuses active runs or unsettled attempts and preserves all daily limits and recorded spending. This command does not run automatically.

Vercel deployment reads the token from root `.env` and passes it through the child process environment, not command-line arguments. Browser CSP restricts resource origins and disables objects and framing; inline scripts remain allowed for the current Next.js rendering setup.

## Attachment recovery

The composer accepts HWP and HWPX alongside TXT, PDF, PNG and JPG. HWP 5 documents
are read from their actual body sections, including compressed and distribution
documents. Nested paragraph text in tables, text boxes, headers, footers and notes
is retained, as is equation source text. HWPX sections follow the package's spine
order. Preview streams are never used as a substitute for the full body.

Extraction is text based: original page layout, embedded images and charts are not
rendered or OCRed. Image-only documents must be attached as PNG/JPG for OCR. HWP 3
(Hancom 97) and earlier formats require saving as HWPX. Password encryption and
DRM require an unlocked copy; they report specific recovery messages. The existing
20,000-character extraction cap and model context cap still apply, with truncation
shown in the preview and answer. The PDF-specific 20-page cap does not apply to HWP.

HWP containers and HWPX package signatures are checked independently of browser
MIME values. Parsing runs in the existing bounded worker subprocess, with internal
stream, decompression and XML limits. DTDs and external XML entities are rejected.
The new Python dependencies are included in `uv.lock` and the existing Docker
build; no desktop office installation or external document service is required.
Run `uv run pytest -q tests/test_hangul.py tests/test_extract.py` for format cases.
The harness integration tests also exercise upload, worker extraction, preview,
model context and follow-up questions with generated HWP/HWPX documents.

The composer saves pending attachment IDs and filenames per account and conversation in session storage. Reloading refreshes each attachment from the API. Unavailable or expired files remain visible with recovery instructions and block submission until resolved or removed. Extracted file content is not copied into browser storage. Network failures preserve the question and explain how to retry.

Follow-up questions reuse the latest successful attachment set in the same conversation. Supplying new attachments replaces that set for subsequent questions. Only submitted sources are eligible; unsubmitted uploads and other conversations are excluded. Expired, deleted or missing sources stop the answer before a model call and request reattachment. Context limits still apply and retain the existing truncation notice.

Image OCR compares automatic layout with a single text block using Tesseract confidence and recovered text. Automatic ordering is retained unless the block pass recovers substantially more confident text. Low-confidence extraction is rejected with guidance to upload a clearer image or TXT. These scores cannot guarantee completeness, so the composer also asks users to compare the preview with the original. The Korean notice regression fixture reproduces issue #4 at 1100 by 420 pixels with Noto Sans CJK Korean Regular, 38px. Run the extraction tests with Korean and English Tesseract data installed to exercise it.
