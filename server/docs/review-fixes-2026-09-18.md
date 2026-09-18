# Review fixes verified on 2026-09-18

## Applied

- Landing page exposes configured administrator login and Google login. Login configuration is optional in Compose. Historical guest billing records remain solely for late settlement; guest access stays disabled.
- Administrator failures are counted per server-resolved source address. Forwarding headers supplied by callers cannot change the bucket. Caddy replaces forwarded addresses and the unpublished API trusts its internal proxy.
- Input budget defaults to 16,384 estimated tokens. Hangul and CJK use two tokens per character before framing and headroom. Source trimming finds the longest fitting prefix. Pretruncated extraction is also disclosed. The answer displays a persistent notice outside its details, including while streaming.
- Provider adapters distinguish explicit HTTP rejection or connection establishment failure from ambiguous read/write failures and interrupted streams. Only known unsubmitted/rejected calls release reservations at zero cost. Historical unknown charges remain pending.
- Operator recovery from paid blocking is available through `python -m modurouter.billing_review USER_ID --reviewed`. It refuses active runs and pending charges and preserves spending and daily quotas.
- Dark semantic colors meet text contrast requirements. Settings initially focus Close. Hidden upload input is absent from accessibility navigation. Disabled primary controls differ visibly. Expanded answer details retain top alignment with readout controls.
- Saved run error codes have user-facing reasons. Failure messages are shown once, failed live questions return to the composer, and a retry-input action remains available after reload. Last selected conversation is restored per user. Mobile Enter inserts a newline.
- Structured TXT content is kept as inert text when libmagic detects JSON or textual markup. Binary images still require matching types. PDF extraction tolerates repairable structure errors while preserving page, encryption, size and resource limits. File-size errors use configuration.
- Vercel token is passed in the child environment instead of command-line arguments. CSP headers restrict origins, embedding and object content. Deleted Google accounts redirect to a readable login error. Duplicate import removed.
- `.ops/` contains exactly `deploy.sh` and `run.sh`. The former database and test artifacts were moved intact to ignored `server/.runtime/` after clean database shutdown. Root `.env` remains mode 600.

## Validation

- Backend: 122 tests passed against local MariaDB. Ruff passed across backend, tests and scripts.
- Client: TypeScript check, four unit tests and production build passed.
- `docker-compose --env-file ../.env config --quiet` passed without printing resolved secrets.
- A 5,709-character Korean source reached the mock model intact, including its final sentence. The saved run did not indicate truncation. Separate regression checks cover budget-filling prefix selection and already-truncated input.
- Provider tests cover 400/401/429/500/503 rejection, connection failures, ambiguous timeouts, partial streaming and paid reservation release.
- Login tests verify source isolation, lock expiry and forged forwarding headers. Billing recovery, structured TXT and repairable PDF tests passed.
- Headless Chrome UI checks used the production client with synthetic API routes, not live provider calls. Verified administrator entry, initial settings focus, error deduplication, draft restoration, conversation restoration, visible truncation notice, hidden upload input and mobile newline behavior.
- Screenshots inspected at widths 360, 768 and 1440 in both themes. Horizontal overflow was zero. Measured danger/accent contrast: light 6.42/6.83, dark 10.43/10.98.
- Local Base UI references: `dialog/demos/hero/css-modules/index.tsx` and `dialog/types.md` in `/Users/johnnybae/peer-design/examples/base-ui/components`. Installed and reference versions are both 1.7.0.

## Limits and deferred low-priority items

No deployment was performed. Live provider quality and live Google OAuth were not retested.

Token counting remains an estimate across providers. Extraction still has a 20,000-character and 20-page limit. No multi-pass whole-document summarizer was added.

Clients sharing one NAT or Vercel egress address share its login throttle. Trusting original client addresses through an additional proxy requires an authenticated forwarding design; arbitrary browser headers are deliberately ignored.

The current static Next.js rendering setup still permits inline scripts in CSP. Nonce-based CSP was not introduced.

The existing 24-hour routing-reliability query and the expected anonymous `/v1/me` 401 console entry were left for a separate performance/authentication refinement. `UPSTAGE_API_KEY` is now used by the concurrently added provider support and was preserved.

The test suite emits an existing Authlib deprecation warning and the intentional oversized-image warning. Neither is a test failure.
