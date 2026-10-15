# Scientific and engineering self-audit

This is an implementation self-audit, not independent external scientific approval.
The full master-prompt definition of done remains incomplete.

| Gate | Evidence | Verdict |
|---|---|---|
| Real satellite acquisition | Eight historical and two 2025/2026 L2A scenes; provider metadata and local band COG hashes | Executed |
| Calibrated geospatial preprocessing | Six-band reflectance, 30 m local UTM, nearest labels, SCL exclusions, buffer, aligned before/after grids | Executed; residual registration/atmosphere remain |
| Historical habitat labels | Hansen annual codes, land and baseline canopy masks; visual/programmatic checks | Constructed and verified as reference data; no independent field labels |
| Genuine neural optimization | Four runs, 187 epochs; measured parameter changes; best/last checkpoints | Executed |
| Held-out evaluation | Whole-region validation, geographic and earlier-year İzmir test; baseline comparisons | Executed on selected reference cohort; insufficient independent scientific closure |
| Calibrated ecological probability | Brier/ECE diagnostics and seed disagreement exist; no calibration/field study | Not established; scores explicitly uncalibrated |
| On-demand real inference | Persistent live Milas API/worker job, exact 2025/2026 source dates, COG/GeoJSON | Executed; September one-year domain unvalidated |
| Map and comparison | Actual browser source images, AOI/polygons, drawing controls, before/after slider, layer opacity, pixel inspection | Verified locally |
| Reports | Actual PDF/CSV/GeoJSON/JSON export endpoints; two-page PDF visually inspected | Verified locally |
| Observed thermal activity | Public NASA MODIS 24-hour NRT snapshot, hashes, per-point acquisition/sensor/confidence | Acquired; AOI zero detections is not absence of fire |
| Prospective fire model | Target, label builder, gates, baselines and architecture implemented | Real data acquisition/training/evaluation NOT RUN; serving blocked |
| Weather temporal authority | Requires observed and available timestamps <=T; no verified as-of archive | Blocked; reanalysis cannot stand in for prospective evidence |
| Habitat fragmentation/stress/transitions | Binary gross tree-cover-loss-reference model only | Not implemented as distinct validated outputs |
| Historical fire density | Historical adapter requires key/archive coverage | Not integrated |
| Containers / PostgreSQL | Dockerfiles, Compose, migration and backend queue path present | NOT RUN locally; Docker unavailable |
| CI | Workflow for Python tests/lint and frontend build/audit/tests | Definition present; no remote execution |
| Production operations | Local loopback deployment, bounded jobs, no admin mutation/upload endpoint | Multi-user auth, distributed quotas, durable artifact store, database upgrades incomplete |
| External ecological pilot | No field labels, expert feedback or partner engagement | Not performed; no collaboration invented |

## Defects found and corrected

- Request geometry tuples versus cached JSON lists caused false cache mismatches. Canonical JSON geometry and a cache-integrity regression test now cover it.
- Coastal water was initially included in the denominator for clear **land** coverage. The denominator now explicitly excludes SCL water while retaining cloud/nodata pixels. Masked water is never used as environmental change.
- The installed MapLibre 5 line had a reported critical sanitizer vulnerability. Upgraded to 6.14.0; final npm audit reports no vulnerabilities.
- MapLibre 6's worker module was not served correctly by the framework bundle. Explicit local worker/shared module assets now render actual vector layers; verified in the browser.
- Initial saved-job load did not update the input date fields, leaving a result/source mismatch in the UI. Saved job geometry and dates now load together.
- MODIS CSV lacks an `instrument` column. Sensor inference is now provider-specific rather than incorrectly defaulting every record to VIIRS; regression-tested.
- Raw HTTP exceptions and INFO URL logging could expose a FIRMS MAP_KEY. Errors are sanitized, and credential-bearing httpx INFO logging is disabled.
- Job capacity admission is serialized in local SQLite mode; PostgreSQL uses an advisory admission lock and row locks, including expired leases. The PostgreSQL path still requires actual integration testing.
- Resume after no validation improvement could pair the older selected checkpoint with a newly timestamped configuration. The selected checkpoint retains its own configuration; an actual-artifact resume regression exercises this case in an isolated test directory.
- PDF maps originally separated large source images across excessive pages. The final two-page report groups before/after imagery and includes an annotated source map, index table, coverage, uncertainty and limitations; both pages visually verified.
- A final rebuild while the standalone frontend was running hit a Windows directory lock. The owned preview was stopped, rebuilt and restarted; README now documents that requirement. Data and model artifacts were unaffected.

## Remaining scientific weaknesses

The training cohort has just two areas, validation one predominantly positive area, and test
one selected external area. High pixel-level agreement cannot be extrapolated to Türkiye,
habitat quality or distinct disturbance causes. The primary neural model does not outperform
the delta-NBR baseline in this test; the second seed does not justify choosing it by test
score or asserting a general deep-learning advantage. Spatially correlated pixels, year-2000
canopy context, Landsat algorithmic references and reference omission/commission errors remain.

No independent event/plot confidence interval, unbiased area estimator, probability
calibration, phenological multi-observation persistence test, automatic registration repair,
or new-season validation exists. The recent Milas map is a model-generated hypothesis.
An artifact hash verifies integrity, not ecological truth or owner/scientific approval.

## Verification record

The latest executed checks and local screenshots are recorded in `verification.json`.
Clean CI explicitly skips real-artifact integration cases when the ignored checkpoint/data
are absent; the remaining tests include synthetic unit/contract fixtures clearly isolated
from scientific datasets. No unexecuted checks are represented as passing.
