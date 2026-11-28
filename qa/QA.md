# ApexVoice QA and production readiness

## Reproduce the offline checks

From the repository root, use Python 3.12, Redis 7 with `redis-server` and `redis-cli`, and a clean virtual environment.

```sh
python -m pip install -r requirements.txt -r qa/requirements.txt
python -m qa.run_legacy
python -m pytest -q qa/test_calls.py qa/test_tenant_contract.py
python -m qa.benchmark --check --output /tmp/apex-benchmark.json

python -m playwright install chromium
git fetch origin 1567c013da05ea75af76e492449c93ecf4b24ae6
commercial=$(mktemp -d)
git archive 1567c013da05ea75af76e492449c93ecf4b24ae6 static/commercial | tar -x -C "$commercial"
python -m pytest -q qa/test_commercial.py \
  --commercial-root "$commercial/static/commercial" --commercial-snapshot

python -m pip install bandit==1.9.4 pip-audit==2.10.1
bandit -r -lll app.py api config.py database.py telephony.py voice_engine.py
pip-audit -r requirements.txt
# Run the historical review with default rules to see reviewed fixture alerts.
gitleaks --config /dev/null git --log-opts=HEAD --redact=100

bash qa/container_smoke.sh linux/arm64
python -m qa.production_gate
```

The Python harness uses an ASGI test client, temporary SQLite, an isolated Redis socket, synthetic credentials, and in-process HTTP provider responses. The Python network guard rejects non-loopback connections, and Playwright fulfills all page requests locally. The container starts with networking disabled and staging enabled. Package installation, advisory queries, browser installation and the Docker build require network access. The benchmark models post-STT traffic. Its partial speech and noise cases start at the transcript boundary, so they provide no evidence about actual transcription accuracy or interruption handling on a phone.

## Verified results

Baseline was `971fb58` on `main`, with Chromium fixtures from the pinned PR #7 snapshot. Local verification used Linux x86-64 and Python 3.12.14. See the PR checks for runner-specific results.

| Check | Result |
| --- | --- |
| Standalone regression scripts | 25 passed. Each ran in a fresh process with a temporary database and stripped environment. |
| New call tests | 31 passed. The integrated tenancy contract collected 12 checks and skipped them while the fixture is pending. |
| PR #7 in Chromium | 4 passed, 1 expected failure for duplicate calendar controls on the pinned snapshot. |
| PR #9 standalone tenancy package | 82 passed across auth/RBAC, isolation, usage and lifecycle at `ce2c7fe`. |
| Dependency scan | 15 resolved runtime packages, zero known advisories reported by PyPI. Production requirements use version ranges, so this result applies to this resolution. |
| Bandit | Zero high severity, nine medium and six low. Medium results included URL opener scheme checks, host binding, temporary storage and SQL string construction. The gate fails on high-severity results. |
| Redacted secret scan | Three initial generic alerts matched an empty API key next to a public voice ID and two synthetic fixtures. Scanner allowances are limited to those patterns and files. |
| Native ARM64 | All 15 Python 3.12 runtime packages resolved as ARM64-compatible wheels. CI builds the existing image on a native ARM runner and checks non-root startup, the writable state directory, build-context exclusions and no-spend health. OCI-host performance remains unverified. |
| Production promotion | Intentionally blocks while the tracked evidence entries are open. |

Benchmark run with 80 synthetic calls, 400 health requests, eight client threads and 20 ms each of injected LLM and TTS delay. These measurements include the application and ASGI client overhead. They exclude real carrier, STT, Internet and provider queueing latency.

| Stage | p50 | p95 | p99 |
| --- | ---: | ---: | ---: |
| Inbound cXML | 33.09 ms | 73.49 ms | 92.35 ms |
| Stub LLM | 20.15 ms | 21.08 ms | 39.23 ms |
| Stub TTS | 20.09 ms | 21.33 ms | 41.76 ms |
| Gather cXML | 58.46 ms | 108.90 ms | 133.96 ms |
| Audio retrieval | 2.77 ms | 14.96 ms | 48.84 ms |
| Inbound through first turn audio retrieval | 95.36 ms | 207.17 ms | 218.82 ms |
| Terminal callback | 11.33 ms | 37.74 ms | 62.84 ms |
| Health under concurrent requests | 13.72 ms | 16.57 ms | 19.49 ms |

The run sustained 7.76 sequential calls/sec and 572 health requests/sec. RSS grew by 2,180 KiB, open file descriptors finished at 7, and SQLite grew by 106,496 bytes. The audio cache added 80 entries for 80 distinct replies. This short run identifies retention behavior. An extended soak is needed to quantify its impact with real audio sizes.

## Findings and release blockers

Severity reflects the plausible impact in production. Source findings identify missing controls and code paths for remediation. The tests exercise routine protective behavior with synthetic inputs.

| Severity | Finding | Release evidence needed |
| --- | --- | --- |
| Informational | Gitleaks flagged a public voice ID and two synthetic test fixtures in Git history and the current tree. The CI configuration allows only those patterns in their original files. | Review the redacted history triage with the next production release. Rotate or revoke any actual credential found by a future scan. |
| High | The inbound webhook handlers buffer request bodies before signature verification. The built-in webhook limiter is staging-only. Gather processing has no persisted per-turn idempotency marker or bounded freshness window. Admission and terminal settlement do have separate idempotency controls. | Demonstrate a configured body and request-rate limit at ingress, bounded callback freshness, and exactly one model, TTS and message operation for each carrier turn, including retry and concurrent delivery. |
| High | The receptionist prompt discourages disclosure and false promises, but the application passes upstream model text to speech and accepts allowlisted tool data with field-name filtering. There is no deterministic speech or receipt check. Fallback tests pass when the provider is unavailable. | Prove confidential data stays outside model context and public responses. Require backend receipts before claims of booking, notification, or transfer. Verify only authorized, schema-validated actions can run. |
| High | Emergency guidance is prompt-driven. The current cXML call path offers speech and hangup without a verified live human handoff. An HTTP hangup failure leaves the call active until recovery. | Verify a deterministic emergency fallback and explicit outcomes for human availability, refusal and timeout. Prove a carrier-enforced call cutoff, signed terminal accounting and provider-side spending controls. |
| High if enabled for external customers | Main still uses global call control and shared operator authentication. The tenancy package in PR #9 is not wired into the API. | Run the integrated two-tenant suite against the commit that first exposes tenant routes. Require no unauthorized reads, writes, routing, clip access or ledger mutations before customer rollout. |
| Medium | The in-process TTS dictionary adds distinct audio entries without a time or size bound. The app also synthesized the repeated greeting on every measured call despite producing a stable clip ID. Local SQLite histories grow as calls accumulate. Raw exception strings can reach diagnostics. | Bound and expire audio entries, verify reuse and deletion across processes, define transcript/inbox retention, and assert logs redact nested and free-text sensitive data. |
| Medium | PR #7 duplicates calendar control IDs. The preview download failed in Chromium. The chat control produced a request-only file. Source review also found the dashboard expects flat message data while the backend emits a nested `message` object, and the disconnect handler leaves rendered data in the tab. | Fix the calendar controls and run the browser suite on the updated commercial assets. Verify populated dashboard rendering with the actual backend schema and clear rendered sensitive data on disconnect. |
| Medium | The container previously copied the build context without a Docker ignore file, which could include local credentials, database state and Git history. | This branch adds build-context exclusions. The ARM64 smoke check verifies ignored files stay out of the image. |

Proposed initial production targets are zero unresolved critical or high findings, zero unreceipted action claims, zero duplicate side effects, and zero cross-tenant disclosures or mutations. On the intended Oracle VM, run a 60-minute synthetic soak with at least 1,000 call sessions and eight concurrent dashboard clients. Require health p95 ≤250 ms, mocked call pipeline p95 ≤1,000 ms, ≤2 retained descriptors over warmup, and ≤256 MiB RSS with no sustained growth above 1 MiB/min in the final 30 minutes. Measure real speech-end-to-first-audio p95 ≤2.5 s in an independently approved provider trial. Use production-matched networking, storage and resource limits in that trial.

## Tenant fixture

The forthcoming integration supplies a pytest plugin exposing a function-scoped `tenant_world` fixture. It starts an isolated in-process ASGI client and seeds two authenticated tenants with unique records. The mapping contains `client`, `owner` and `other` entries. Each tenant has `id`, `token`, and `records` keyed by `calls`, `messages`, and `appointments`. The top-level mapping also has `missing_record` with syntactically valid, absent IDs per resource and `valid_updates` with valid message and appointment PATCH bodies. Callbacks, media and Redis namespace checks should be added to the fixture when the integrated backend defines those seams.

```sh
python -m pytest qa/test_tenant_contract.py -p tenancy_qa_fixture \
  --tenant-fixture-plugin tenancy_qa_fixture
```

This suite skips while the integration fixture is absent. Storage-level coverage from PR #9 is separate from this gate.

## CI and deployment

The `ApexVoice required checks` job requires the Python, Chromium, scanner and ARM64 jobs to succeed. Configure that exact check as required on `main` after the workflow is adopted. The `ApexVoice production readiness` reusable workflow calls the same offline gates and then verifies the reviewed evidence manifest. Production deployment or promotion jobs should depend on that workflow for the exact candidate revision. Protect changes to the evidence manifest through the same review requirements as a release.

The current Render blueprint has auto-deploy disabled. The existing Vercel Git integration needs its promotion rule wired to the check in project settings, and Oracle deployment needs the same gate in its release pipeline. GitHub branch protection settings returned HTTP 403 to the integration, so this branch leaves remote protection settings unmodified.
