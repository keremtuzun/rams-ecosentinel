import copy
from datetime import date

import numpy as np
import pytest
import rasterio
from shapely.geometry import box, mapping

from ecosentinel.common import DataUnavailable
from ecosentinel.geometry import AnalysisRequest, validate_geometry
from ecosentinel.raster import aoi_mask, clear_mask, indices, make_grid, reflectance_parameters, write_raster
from ecosentinel.sources import hansen_url, parse_firms, provider_url


def request():
    return {
        "geometry": mapping(box(28.23, 37.02, 28.25, 37.04)),
        "before_start": "2020-06-01",
        "before_end": "2020-06-30",
        "after_start": "2022-06-01",
        "after_end": "2022-06-30",
    }


@pytest.mark.parametrize(
    "geometry",
    [
        mapping(box(0, 0, 1, 1)),
        mapping(box(25, 35, 44, 42)),
        {"type": "Polygon", "coordinates": [[[28, 37], [28.1, 37.1], [28, 37.1], [28.1, 37], [28, 37]]]},
        {"type": "Point", "coordinates": [28, 37]},
        {"type": "Polygon", "coordinates": []},
    ],
)
def test_reject_invalid_aoi(geometry):
    with pytest.raises(ValueError):
        validate_geometry(geometry)


@pytest.mark.parametrize(
    "replacement",
    [
        {"after_end": "2099-01-01"},
        {"before_start": "2020-07-02"},
        {"before_end": "2020-09-01"},
        {"after_start": "2020-06-15", "after_end": "2020-06-30"},
        {"after_start": "2022-12-01", "after_end": "2022-12-31"},
    ],
)
def test_reject_invalid_dates(replacement):
    with pytest.raises(ValueError):
        AnalysisRequest.model_validate({**request(), **replacement})


def test_valid_request():
    assert AnalysisRequest.model_validate(request()).before_start == date(2020, 6, 1)


def test_georeferenced_roundtrip(tmp_path):
    grid = make_grid(request()["geometry"])
    values = np.ones((6, grid.height, grid.width), np.float32) * 0.2
    write_raster(
        tmp_path / "source.tif",
        values,
        grid,
        descriptions=["blue", "green", "red", "nir", "swir16", "swir22"],
    )
    with rasterio.open(tmp_path / "source.tif") as source:
        assert source.crs.to_epsg() == 32635
        assert source.transform == grid.transform
        assert source.width == grid.width and source.height == grid.height
        assert source.descriptions[3] == "nir"
        np.testing.assert_array_equal(source.read(), values)
        assert source.tags(ns="IMAGE_STRUCTURE")["LAYOUT"] == "COG"
    assert aoi_mask(request()["geometry"], grid).mean() > 0.9
    assert 28.1 < grid.wgs84_bounds()[0] < 28.24


def test_clouds_shadows_and_buffer():
    scl = np.full((15, 15), 4, np.float32)
    scl[7, 7] = 9
    scl[1, 1] = 3
    scl[13, 13] = 6
    valid = clear_mask(scl)
    assert not valid[7, 7] and not valid[7, 9] and valid[7, 10]
    assert not valid[1, 1] and not valid[13, 13]


def test_scaling_does_not_double_apply_offset():
    asset = {"raster:bands": [{"scale": 0.0001, "offset": -0.1}]}
    item = {"properties": {"earthsearch:boa_offset_applied": True, "s2:processing_baseline": "05.00"}}
    scale, offset = reflectance_parameters(item, asset)
    assert 2000 * scale + offset == pytest.approx(0.2)
    item["properties"]["earthsearch:boa_offset_applied"] = False
    with pytest.raises(DataUnavailable, match="Ambiguous"):
        reflectance_parameters(item, asset)
    with pytest.raises(DataUnavailable, match="metadata missing"):
        reflectance_parameters(item, {})


def test_indices_use_calibrated_band_order():
    bands = np.array([0.1, 0.1, 0.2, 0.6, 0.3, 0.1], np.float32).reshape(6, 1, 1)
    result = indices(bands)
    assert result["ndvi"].item() == pytest.approx(0.5)
    assert result["ndmi"].item() == pytest.approx(1 / 3)
    assert result["nbr"].item() == pytest.approx(5 / 7)
    assert np.isfinite(list(indices(np.zeros_like(bands)).values())).all()


def test_firms_observation_is_not_prediction():
    csv = "latitude,longitude,acq_date,acq_time,confidence,frp,scan,track\n37.1,28.3,2021-08-02,930,n,12.2,0.4,0.4\n"
    result = parse_firms(csv)
    observation = result["features"][0]
    assert observation["geometry"]["coordinates"] == [28.3, 37.1]
    assert observation["properties"]["acquired_at"] == "2021-08-02T09:30:00+00:00"
    assert observation["properties"]["meaning"] == "observed thermal anomaly"
    assert parse_firms(csv, [30, 38, 31, 39])["features"] == []
    modis = parse_firms(csv, source="MODIS_C6_1_NRT_PUBLIC_24H")
    assert modis["features"][0]["properties"]["sensor"] == "MODIS"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/private.tif",
        "https://example.com/file.tif",
        "https://storage.googleapis.com@127.0.0.1/a.tif",
        "https://storage.googleapis.com/a.tif?token=secret",
    ],
)
def test_asset_allowlist(url):
    with pytest.raises(DataUnavailable):
        provider_url(url)


def test_hansen_source_version_and_tile():
    assert "GFC-2025-v1.13_lossyear_40N_020E.tif" in hansen_url("lossyear", 28, 37)


def test_split_buffer():
    from ecosentinel.dataset import check_splits

    rows = [
        dict(id="a", split="train", bbox=[28, 37, 28.1, 37.1]),
        dict(id="b", split="validation", bbox=[29, 37, 29.1, 37.1]),
        dict(id="c", split="test", bbox=[30, 37, 30.1, 37.1]),
    ]
    check_splits(rows)
    overlap = copy.deepcopy(rows)
    overlap[2]["bbox"] = [28.11, 37, 28.15, 37.1]
    with pytest.raises(ValueError, match="buffer"):
        check_splits(overlap)
