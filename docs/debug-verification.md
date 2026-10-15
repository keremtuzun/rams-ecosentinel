# End-to-end debugging, 15 October 2026

Baseline: clean local and fetched remote `main`, commit `95ab6a5acfc235e2d907d273f3bfa0ee0da43035`.
Its GitHub Actions run `38715486886` succeeded. Both production projects were READY.
No user changes were present. Scientific thresholds, model weights, serving provenance,
country/area/grid/date/season bounds and private artifact access rules are preserved.

## Reproduced defects and corrections

| Problem and root cause | Correction | Regression evidence |
|---|---|---|
| Slow external basemap tiles prevented drawing initialization: layers waited for the map's full `load` event. | Initialize interaction layers at `style.load`. | A browser test holds Esri requests open: failed before the fix, passes after; drawing/cancel works before tile completion. Existing crossing/undo/double-click tests also pass. |
| Reload selected an older successful result after the latest job failed. | Select the newest created job, including failures, and show its actual error. | Browser reproduction failed before the fix; latest failed request now stays selected. |
| A delayed initial history response replaced a user's newer place selection. | Apply initial results only while their selection version is current. | A controlled delayed response reproduced the overwrite; the browser now retains Ankara. |
| Only two-year endpoint spacing was checked in the client; blank, invalid, future, overlapping, long or seasonally incompatible windows could be sent. The local server's date cutoff depended on OS timezone. | Validate all four ISO dates and all existing server rules before both scene discovery and job creation; use UTC today on both sides. | Calendar anniversary/leap-day, actual ordinal-season rule, 62-day, invalid/blank/future and UTC-midnight checks. Rules remain 2017+, >=2 calendar years, <=62 days/window, <=3653 days overall, <=45 ordinal-season days. |
| Compute timeouts, child crashes and unexpected infrastructure errors were all returned as terminal HTTP 422. Catalogue/raster network failures were indistinguishable from unsuitable observations. | Return retryable 503 for infrastructure failures; retain terminal 422 for genuine data/validation rejection. | Three service fixtures reproduced 422 before the fix. Network, lease expiry, stale owner, duplicate delivery, commit-then-dispatch failure and the two-attempt cap are tested. |
| A first failing cloud request dropped its newly signed session cookie, potentially losing ownership of an already recorded job. | Preserve cookie and private/no-store headers on exception responses. | A first-request 503 fixture reproduced the missing cookie before the fix; signatures and forged/missing ownership remain tested. |
| Admission could persist a job without delivering the initial message, leaving it queued forever; the UI did not recover the recorded job after a lost response. | Reading an undelivered queued job after 30 seconds retries the same idempotency key, without new quota admission. Expired jobs become explicit failures after 24 hours. The browser retrieves the matching newly recorded request without another POST. | Recovery, retention expiry and one-POST browser regressions; quota conflict/idempotency tests preserve three/browser/hour and eight globally. No production quota exhaustion test. |
| HTML gateway failures produced JSON parse exceptions and an unrelated generic warning. | Translate unreadable server responses into a useful connection error. | A 504 HTML response fixture checks the Turkish message. |
| A recovered poll retained the previous connection error, and opening a new analysis retained the old report beside the draft. | Clear transient warnings after confirmed progress and clear the displayed report when starting an inactive draft. | Both browser regressions failed before correction; recovered polling and draft/result separation are checked. |

## Local verification

Commands mirror `.github/workflows/ci.yaml`, with additional TypeScript and compute-service checks:

```text
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check ecosentinel tests apps/backend/app.py
.venv/Scripts/python.exe -m ruff format --check ecosentinel tests apps/backend/app.py
cd apps/web
npm run build
npm run typecheck
ECOSENTINEL_HOSTED_MODE=evidence npm test
npm audit --audit-level=high
npx prettier --check app components lib scripts tests playwright.config.ts next.config.ts tsconfig.json package.json
```

The Python suite includes authentic installed artifact/checkpoint tests. UI, concurrency,
network-failure and quality-mask fixtures prove software behavior only. They do not prove
new satellite acquisition, real inference or model accuracy.

Local results: 82 Python cases and 41 frontend/coordination cases passed; production
build, TypeScript, Ruff, formatting and npm high-severity audit passed (zero npm findings).
Two browser cases were rerun successfully after a host suspension/DNS interruption;
the interrupted run itself is not recorded as a clean pass. Remote CI is a separate check.

Existing triangle/concave tests confirm that padding outside the requested polygon does
not enter the clear-data denominator or output masks. Cloud/water/missing pixels within
the selected area still trigger the original 80% land-clear and 65% joint-data gates.

## Live verification boundary

`node scripts/verify_live.mjs` runs read-only browser checks. The initial production run
passed logo, guide, rendering and overflow checks at 320/390/768/1440 px without submitting
an analysis. `--submit-real-analysis` explicitly opts into one genuine new request, and
`--resume` inspects that same request without another POST. Session state, result files,
screenshots and detailed evidence stay under ignored `artifacts/deployment/debug/`.
The script uses the public browser/API path and never calls the privileged compute API
directly or publishes fixtures.

Release commit, remote CI, both deployment IDs/states and actual cloud-run evidence are
recorded in ignored `artifacts/deployment/debug/release-verification.json` after execution. Live results must be
reported separately from local test passes.

Containers/PostgreSQL, destructive production fault injection, production quota exhaustion
and independent scientific validation are NOT_RUN. Client disconnects and refresh can be
tested on the real job; deterministic server crash/retry/concurrency behavior is fixture
evidence, not an induced production outage.
