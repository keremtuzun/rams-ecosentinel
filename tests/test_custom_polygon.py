"""Geometry/quality regression fixtures only; never published as analysis results."""

import numpy as np
import pytest
from shapely.geometry import Polygon, mapping

from ecosentinel.common import DataUnavailable
from ecosentinel.raster import aoi_mask, joint_valid_mask, make_grid


@pytest.mark.parametrize(
    "points",
    [
        [(31.27, 37.02), (31.29, 37.02), (31.27, 37.04)],
        [(31.27, 37.02), (31.29, 37.02), (31.29, 37.023), (31.273, 37.023), (31.273, 37.04), (31.27, 37.04)],
    ],
)
def test_clear_triangle_and_concave_area_ignore_only_padding(points):
    geometry = mapping(Polygon(points))
    grid = make_grid(geometry)
    inside = aoi_mask(geometry, grid)
    # The previous valid.mean() calculation incorrectly rejected both shapes.
    assert inside.mean() < 0.65
    valid = joint_valid_mask(inside, inside, geometry, grid)
    np.testing.assert_array_equal(valid, inside)
    assert valid[inside].mean() == 1


def test_cloud_or_water_inside_custom_area_still_enforces_same_65_percent_gate():
    geometry = mapping(Polygon([(31.27, 37.02), (31.29, 37.02), (31.27, 37.04)]))
    grid = make_grid(geometry)
    inside = aoi_mask(geometry, grid)
    flat_inside = np.flatnonzero(inside)
    clear = np.ones_like(inside)  # Even clear padding must never improve the score.
    clear.flat[flat_inside[: int(len(flat_inside) * 0.36) + 1]] = False
    with pytest.raises(DataUnavailable, match="Insufficient jointly clear"):
        joint_valid_mask(inside, clear, geometry, grid)
    clear.flat[flat_inside] = False
    clear.flat[flat_inside[: int(len(flat_inside) * 0.66) + 1]] = True
    valid = joint_valid_mask(inside, clear, geometry, grid)
    assert 0.65 < valid[inside].mean() < 0.67
    assert not valid[~inside].any()


def test_report_clear_fraction_uses_selected_area_and_masks_padding(tmp_path, monkeypatch):
    import rasterio
    import ecosentinel.inference as inference
    from ecosentinel.common import PREPROCESSING

    geometry = mapping(Polygon([(31.27, 37.02), (31.29, 37.02), (31.27, 37.04)]))
    grid = make_grid(geometry)
    inside = aoi_mask(geometry, grid)
    bands = np.full((6, grid.height, grid.width), 0.2, np.float32)
    bands[3] = 0.6
    meta = {"grid": grid.metadata(), "preprocessing": PREPROCESSING, "acquired_at": "2024-06-20T09:00:00Z"}
    # A deterministic test-only score isolates report accounting from the model.
    monkeypatch.setattr(inference, "ARTIFACTS", tmp_path / "no-models")
    monkeypatch.setattr(
        inference,
        "load_model",
        lambda *a: (
            None,
            {"bands": "multispectral", "temporal": True, "threshold": 0.5},
            {"checkpoint_sha256": "fixture-only"},
        ),
    )
    monkeypatch.setattr(inference, "tiled_scores", lambda *a, **k: np.zeros(inside.shape))
    report = inference.infer_pair(bands, bands, inside, grid, meta, meta, tmp_path, geometry=geometry)
    assert report["clear_fraction"] == 1
    assert report["eligible_pixels"] == inside.sum()
    assert report["candidate_pixels"] == 0
    with rasterio.open(tmp_path / "score.tif") as source:
        assert np.all(source.read(1)[~inside] == source.nodata)
