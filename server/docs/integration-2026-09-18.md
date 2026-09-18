# Interface and backend integration

PR #7 is integrated with main `00a2bf3` and the newer local changes captured in `e0087d3`. The frontend branch's earlier base must not revert subsequent fixes.

## Preserved behavior

- Glass UI, age modes, composer resizing, copy, regeneration and response progress from PR #7.
- Provider-qualified manual selection, automatic routing and strictly free routing. Model prices and provider eligibility still come from the backend catalog.
- Runtime administrator policies, provider activation, per-account limits, pricing refresh and optimistic revision checks.
- Attachment extraction including HWP/HWPX, upload status recovery, preview and follow-up context restoration.
- Google/admin/guest sessions, conversation history, cancellation, idempotent retries and actionable network errors.
- Model/provider events during streaming, saved response recovery and request limits introduced by recent main commits.
- OpenAI `gpt-4o-mini-transcribe`, 600-second audio limits, server chunking and separate speech accounting.
- Korean browser text-to-speech with delayed voice loading, explicit Korean voice choice and cancellation.

## Reconciled contracts

`GET /v1/models` retains the latest provider-specific catalog and adds supported `efforts` per route. The new UI sends `routing` and optional `reasoning_effort`. The legacy `model` field remains accepted for clients using PR #7's original contract; it remains subject to routing and administrator restrictions. Ambiguous simultaneous `model` and `routing` selections are rejected.

The established API origin/rewrite deployment is retained. PR #7's experimental `/api/backend` handler excluded administrator APIs, uploads, OAuth and deletes, so it is not part of the integrated deployment. Cookies continue to use credentialed requests and the API validates origin and CSRF. The unused local canned-response catalog is removed.

The deployed `0006_speech_requests` revision is unchanged. `0007_routing_choice` adds the latest routing fields and `0008_runtime_settings` adds administrator policy storage. Existing speech accounting rows are preserved. Deployment removes only the two superseded migration filenames, and reloads Caddy so audio body-size and timeout changes take effect.

Speech now uses the effective runtime policy and existing guest/member/admin request limits. Unknown usage retains its reservation; cancelling the request cannot interrupt known-cost settlement. Pending speech costs still require operator review.

## Verification

Server regression coverage includes routing, provider adapters, speech billing, account limits, disabled providers and upgrade from the deployed speech schema. Frontend coverage includes streaming recovery, manual/free routing contracts, attachments, cross-origin credentials and Korean voice selection. Headless browser checks cover desktop and mobile composition, model settings, reply actions and conversation restoration.

UI popover structure was checked against the local Peer Design Base UI 1.7.0 popover example at `examples/base-ui/components/popover/demos/hero/css-modules/index.tsx`. The requested glass appearance is retained.
