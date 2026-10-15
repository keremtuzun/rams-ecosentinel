# Cloud execution verification

Verified on 14 October 2026 UTC (15 October in Türkiye). The public application is
https://rams-ecosentinel.vercel.app; its authenticated Python compute service runs as a
separate Vercel project. No local API or worker participated in this cloud job.

## Actual new request

Job `c0eca3c0-c5dc-44d2-817c-1dc135b151de` requested a new approximately 19 km² area near
Kaz Dağları (26.95–27.00° E, 39.74–39.78° N), comparing June 2024 with June 2026. It was
submitted through the hosted web API and processed through Vercel Queues and FastAPI:

- Earlier image: `S2B_35TME_20240630_0_L2A`.
- Later image: `S2B_35TME_20260630_0_L2A`.
- Jointly valid comparison: 89.04%; 144×149 pixels on the original 30 m UTM grid.
- Three genuine compute stages; final status `succeeded`.
- Eleven private artifacts passed SHA256 and byte-size verification.
- Owned PDF, CSV, GeoJSON and pixel-inspection routes returned HTTP 200. The downloaded
  exports were byte-identical to their private stored artifacts. A request without the
  owning browser session returned HTTP 404.

The first deployment exposed a real conditional-write bug: compressed Blob GET responses
returned weak ETags, while writes required strong validators. This was reproduced against
the actual stored record, and fixed by requesting the exact uncompressed representation
with `Accept-Encoding: identity`. No concurrency protection was disabled. The already
committed earlier image was retained; a recovery queue message routed the same job to the
corrected deployment for later acquisition and inference.

[cloud-run-verification.json](cloud-run-verification.json) records deployment IDs, actual
source metadata, model conversion evidence, result hashes and HTTP checks. It excludes
credentials, session cookies and private storage paths.

## Public browser flow

After promotion, the actual public site was used to search **Yenice, Çanakkale**, select
**30 June 2024** and **30 June 2026**, and press **Analizi başlat**. New job
`f8fa4500-8a37-41f3-8d48-e6ba5f216770` completed all three stages on the corrected deployment
without an administrative recovery message or a local worker. The result appeared with
the chosen dates, genuine before/after images, candidate polygons and export controls.
[cloud-browser-verification.json](cloud-browser-verification.json) records that separate
request and its actual source observations. These candidates are not ground-truth claims.

## Close-date regression

On 15 October 2026 in Türkiye, a user request ending on 30 June 2020 and 29 July 2020
exposed an overlap bug in the simple two-date form. Its two automatically generated
30-day windows shared 30 June. The backend correctly rejected that overlap; the UI
incorrectly translated it into an unrelated generic date-order warning.

Simple-date changes now recompute both search windows, retaining the chosen endpoints
and shortening the later window to begin after the earlier endpoint when needed. Manual
four-date windows retain their exact values and report the actual rejection reason.
No backend quality or nonoverlap check was loosened. Twenty frontend/coordination tests
passed, including the exact pair in either input order and adjacent-date/year-boundary
cases. The real cloud backend accepted the derived 1 July–29 July window.

The user's existing selected area was retained and job
`02f15524-416d-4544-b8a7-52e76f5c7b73` completed all three genuine stages. Its PDF was
downloaded through the public browser and matched the stored SHA256. See
[date-window-fix-verification.json](date-window-fix-verification.json); it omits the
user's geometry, credentials and private storage paths.

## Türkiye-wide 50 km and two-year comparison

New requests support the full Türkiye study extent, bounding dimensions up to **50 km**,
area up to **2,500 km²**, and at least **two calendar years between the chosen endpoints**.
The 30 m grid and trained model are unchanged; the bounded grid is now at most 1670×1670.
Existing historical results with shorter intervals remain readable.

Adjacent real scenes can be assembled within a five-calendar-day span, with each scene's
scaling, acquisition time and used-pixel count retained. Two source-index GeoTIFFs identify
the contributing acquisition for every valid pixel. Missing or cloudy pixels are masked;
the original 80% land-clear and 65% joint comparison quality gates remain in force.

Real job `c0dc5f78-b124-4747-9ed9-44cbdf38eace` processed a 49,995 m bounding dimension near
Ankara, comparing June 2022 with June 2024. It completed all three cloud stages in 206.23 s
on a 1667×1649 grid. Earlier imagery combined two real scenes; later imagery combined
three. Joint valid coverage was 98.32%. Thirteen genuine artifacts were produced. The
27,213,752-byte PDF and 106,804,480-byte index GeoTIFF downloaded with HTTP 200 through
short-lived signed URLs, and their SHA256 digests matched private storage. Large-raster
pixel inspection returned HTTP 200 and correctly preserved a masked center pixel as null.
See [50km-cloud-verification.json](50km-cloud-verification.json).

Testing exposed immutable redirect headers in the download response wrapper. The wrapper
now clones response headers before adding private-cache/session headers. A regression test
uses a native immutable redirect; no private artifact was made public. Sixty-seven Python
tests and 22 frontend/coordination tests passed. Boundary fixtures cover western, central,
northeastern, eastern and southern Türkiye, plus leap-day anniversaries, pixel provenance
and rejection of mosaics spanning more than five calendar days.

Expanded geographic coverage means execution is supported; it is not independent field
validation of model accuracy across Türkiye. The scores remain experimental candidates.

## Runtime and limitations

The ONNX model is converted from the original trained primary checkpoint, SHA256
`c8463288bb16fba7a43d218004fba3851505b34025f33b72bf2b9db657a4b358`. Conversion passed the
predeclared 1e-4 maximum absolute score-error criterion on all four real study regions;
observed maximum error was 0.00001848 with zero threshold-mask disagreements. The secondary
conversion's error was 0.00016636 and failed that criterion. It was excluded, not exempted;
cloud jobs explicitly report two-seed uncertainty unavailable.

The model's change candidates remain experimental and uncalibrated. New geography and
date intervals are not independently field-validated. No wildfire forecast is served.
Cloud processing preserves the original source quality, reflectance and eligibility gates.
Unsuitable dates or insufficient clear imagery end in an explicit failure.

The backend includes a checksum-pinned official Expat build because the minimal Vercel
Linux runtime lacked Rasterio's `libexpat.so.1` dependency. Production validation and the
actual acquisition/inference run exercise that dependency; Docker is still unverified.

## Application checks

Sixteen frontend/coordination tests and 56 Python tests passed during this change. A browser
regression test also covers selecting the latest created job after a page reload, even
when its observation date is earlier than another result. The six
queue coordination tests cover duplicate delivery, committed progress followed by dispatch
failure, stale ownership, explicit data failure, premature stage delivery and forged browser
sessions. These test fixtures are not published analysis evidence. Actual cloud processing
and artifact integrity were checked separately as recorded above.
