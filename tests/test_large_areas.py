"""Boundary and mosaic fixtures only; no fixture becomes published analysis evidence."""

from datetime import date

import numpy as np
import pytest
import rasterio
from shapely.geometry import box, mapping

from ecosentinel.common import DataUnavailable, sha256
from ecosentinel.geometry import AnalysisRequest, validate_geometry
from ecosentinel.raster import acquire_scene, make_grid
from ecosentinel.sources import covering_observations
from tests.test_geospatial import request


@pytest.mark.parametrize("lon,lat", [(26, 40), (33, 40), (41, 40), (44, 38), (36, 36)])
def test_large_areas_across_turkiye_keep_30m_grid(lon, lat):
    geometry = mapping(box(lon - 0.25, lat - 0.2, lon + 0.25, lat + 0.2))
    validate_geometry(geometry)
    grid = make_grid(geometry)
    assert grid.width > 512 and grid.height > 512
    assert grid.width <= 1670 and grid.height <= 1670
    assert grid.transform.a == 30 and grid.transform.e == -30


def test_fifty_kilometre_boundary_is_enforced():
    # At the central meridian this north/south extent slightly exceeds 50 km.
    with pytest.raises(ValueError, match="50 km"):
        validate_geometry(mapping(box(32.99, 39.77, 33.01, 40.23)))


@pytest.mark.parametrize(
    "before,after,accepted",
    [
        ("2020-06-30", "2022-06-29", False),
        ("2020-06-30", "2022-06-30", True),
        ("2020-02-29", "2022-02-28", True),
        ("2024-02-29", "2026-02-27", False),
        ("2024-02-29", "2026-02-28", True),
    ],
)
def test_minimum_two_calendar_years(before, after, accepted):
    before_date, after_date = date.fromisoformat(before), date.fromisoformat(after)
    payload = {
        **request(),
        "before_start": before_date.replace(day=1),
        "before_end": before_date,
        "after_start": after_date.replace(day=1),
        "after_end": after_date,
    }
    if accepted:
        AnalysisRequest.model_validate(payload)
    else:
        with pytest.raises(ValueError, match="at least two years"):
            AnalysisRequest.model_validate(payload)


def test_past_date_cutoff_uses_utc_independently_of_server_timezone(monkeypatch):
    from datetime import datetime, timezone
    import ecosentinel.geometry as geometry

    class Clock:
        @staticmethod
        def now(tz):
            assert tz is timezone.utc
            return datetime(2024, 7, 1, 0, 1, tzinfo=timezone.utc)

    monkeypatch.setattr(geometry, "datetime", Clock)
    payload = {
        **request(),
        "before_start": "2022-06-01",
        "before_end": "2022-06-30",
        "after_start": "2024-06-01",
        "after_end": "2024-07-01",
    }
    AnalysisRequest.model_validate(payload)
    with pytest.raises(ValueError, match="in the past"):
        AnalysisRequest.model_validate({**payload, "after_end": "2024-07-02"})


def fixture_scene(identifier, footprint, acquired):
    return {
        "id": identifier,
        "geometry": mapping(footprint),
        "properties": {"datetime": acquired, "earthsearch:boa_offset_applied": True},
        "assets": {
            band: {"href": identifier + "/" + band, "raster:bands": [{"scale": 0.0001, "offset": 0}]}
            for band in ["blue", "green", "red", "nir", "swir16", "swir22", "scl"]
        },
    }


def test_tile_assembly_rejects_acquisitions_more_than_five_days_apart(monkeypatch):
    import ecosentinel.sources as sources

    geometry = mapping(box(28.23, 37.02, 28.25, 37.04))
    left = fixture_scene("left", box(28.23, 37.02, 28.24, 37.04), "2020-06-30T09:00:00Z")
    right = fixture_scene("right", box(28.24, 37.02, 28.25, 37.04), "2020-06-26T09:00:00Z")
    monkeypatch.setattr(sources, "search_sentinel", lambda *args: [left, right])
    assert len(covering_observations(geometry, "2020-06-01", "2020-06-30")[0]) == 2
    right["properties"]["datetime"] = "2020-06-25T09:00:00Z"
    assert covering_observations(geometry, "2020-06-01", "2020-06-30") == []


def test_real_tile_rules_preserve_pixel_source_assignment_and_cloud_gate(tmp_path, monkeypatch):
    import ecosentinel.raster as raster

    geometry = mapping(box(28.23, 37.02, 28.25, 37.04))
    grid = make_grid(geometry)
    scenes = [
        fixture_scene("left", box(28.22, 37.01, 28.24, 37.05), "2020-06-30T09:00:00Z"),
        fixture_scene("right", box(28.24, 37.01, 28.26, 37.05), "2020-06-30T09:01:00Z"),
    ]
    monkeypatch.setattr(raster, "covering_observations", lambda *args: [scenes])
    clouded = False

    def read_fixture(url, requested_grid, categorical=False):
        assert requested_grid.metadata() == grid.metadata()
        arr = np.full((grid.height, grid.width), np.nan, np.float32)
        split = grid.width // 2
        part = np.s_[:, :split] if url.startswith("left") else np.s_[:, split:]
        arr[part] = (9 if clouded else 4) if categorical else (2000 if url.startswith("left") else 3000)
        if categorical and not clouded and url.startswith("left"):
            arr[:, :4] = 6
        return arr

    monkeypatch.setattr(raster, "read_aligned", read_fixture)
    data, valid, meta = acquire_scene(geometry, "2020-06-01", "2020-06-30", grid, tmp_path / "clear")
    assert meta["mosaic"] and len(meta["observations"]) == 2
    assert meta["water_fraction"] > 0  # Water in the first tile must survive the second tile.
    with rasterio.open(tmp_path / "clear/source_index.tif") as source:
        assignment = source.read(1)
    assert np.all(assignment[~valid] == 0)
    assert set(np.unique(assignment[valid])) == {1, 2}
    for index, scene in enumerate(meta["observations"], 1):
        assert (assignment == index).sum() == scene["used_pixels"]
        np.testing.assert_allclose(data[0][assignment == index], 0.2 if index == 1 else 0.3)
    assert sha256(tmp_path / "clear/source_index.tif") == meta["checksums"]["source_index.tif"]
    clouded = True
    with pytest.raises(DataUnavailable, match="No acceptable"):
        acquire_scene(geometry, "2020-06-01", "2020-06-30", grid, tmp_path / "clouds")
