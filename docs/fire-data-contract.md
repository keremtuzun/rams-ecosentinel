# Fire experiment input contract (not executed on real historical data)

`build-fire-labels` accepts a feature manifest, a NASA FIRMS science CSV and a verified
coverage JSON. It calculates binary target observations in `(T,T+7d]` intersecting the AOI.
It writes beside the feature manifest, preserving relative paths. This is detection in a
future observation window, not a verified ignition or wildfire-caused event label.

Coverage fields: `quality="science"`, `coverage_verified=true`, `archive_sha256`,
`source_url` under the official FIRMS hostname, `product`, timezone-aware `start`, `end`,
and GeoJSON `geometry`. Coverage must come from actual archive/service records; setting a
boolean without that evidence is not legitimate scientific verification.

Each feature record must contain:

- `split`: train, validation or test; `prediction_at`: timezone-aware T.
- `region_id`, `event_group`: curated real geographic/event groups. Their IDs cannot cross partitions.
- `geometry`: the actual target cell, `spatial_target_km=1`, `grid_resolution_m=30`.
- `image_path`: a relative, contained NPZ path, `image_sha256`, `scene_id`,
  `scene_acquired_at`, `scene_available_at` (not merely current retrieval time).
- `preprocessing`: exactly the current `PREPROCESSING` contract.
- NPZ `reflectance`: calibrated six-band 32x32 float array; `valid`: 32x32 cloud/quality mask.
- `weather`: temperature_c, relative_humidity_pct, wind_speed_ms, precipitation_7d_mm,
  soil_moisture and elevation_m, each with `value`, `source`, `observed_at`, `available_at`.
  Actual raw records and publication provenance must accompany these metadata externally.

The generated records add `target`, `label_window_end`, `label_source_quality`,
`label_coverage_verified`, `label_source`, `label_sha256`, and actual `target_observations`.

Validation checks feature valid/publication timestamps <=T, exact seven-day horizon,
science-quality coverage, explicit class support, unique region/event/scene partitions,
geographic buffers, purged chronological windows, preprocessing, image checksums, paths,
dimensions, valid coverage and finite inputs. It cannot automatically authenticate a
curator's external claims; provenance needs review before scientific use.

Fire training compares image-summary/weather logistic regression and Random Forest against
a trainable PyTorch image/weather fusion network. Weather normalization is train-only.
Weighted BCE, validation each epoch, scheduling, early stopping, checkpointing and held-out
metrics are implemented. Fire resume, calibration, operational as-of acquisition and serving
are not implemented. There is no fire checkpoint or prospective-performance claim in this
release. Historical API access and weather archive construction are the next blockers.
