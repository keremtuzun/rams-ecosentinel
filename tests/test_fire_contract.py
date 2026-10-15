import copy

import pytest
from shapely.geometry import box, mapping

from ecosentinel.common import PREPROCESSING
from ecosentinel.fire import WEATHER_FIELDS, validate_fire_records


def records():
    # Synthetic contract records only. No imagery, labels or prospective metrics are fabricated.
    output = []
    for split, year, lon in [("train", 2020, 28), ("validation", 2021, 30), ("test", 2022, 32)]:
        for target in [0, 1]:
            prediction = f"{year}-06-01T12:00:00Z"
            observed = f"{year}-06-01T09:00:00Z"
            output.append(
                {
                    "split": split,
                    "prediction_at": prediction,
                    "label_window_end": f"{year}-06-08T12:00:00Z",
                    "label_source_quality": "science",
                    "label_coverage_verified": True,
                    "target": target,
                    "weather": {
                        key: {
                            "value": 0.1,
                            "source": "test-only",
                            "observed_at": observed,
                            "available_at": observed,
                        }
                        for key in WEATHER_FIELDS
                    },
                    "scene_acquired_at": observed,
                    "scene_available_at": observed,
                    "label_source": "test-only",
                    "label_sha256": "test-only",
                    "scene_id": f"test-{split}",
                    "region_id": split,
                    "event_group": f"{split}-{target}",
                    "grid_resolution_m": 30,
                    "spatial_target_km": 1,
                    "preprocessing": PREPROCESSING,
                    "geometry": mapping(box(lon, 37, lon + 0.01, 37.01)),
                }
            )
    return output


def test_as_of_contract():
    validate_fire_records(records())


@pytest.mark.parametrize(
    "mutation",
    [
        "future_weather",
        "unpublished_weather",
        "future_scene",
        "event_overlap",
        "region_overlap",
        "scene_overlap",
        "nrt",
        "unknown_coverage",
        "wrong_horizon",
        "overlapping_geography",
        "temporal_overlap",
    ],
)
def test_reject_fire_leakage(mutation):
    rows = copy.deepcopy(records())
    if mutation == "future_weather":
        rows[0]["weather"][WEATHER_FIELDS[0]]["observed_at"] = "2020-06-02T00:00:00Z"
    elif mutation == "unpublished_weather":
        rows[0]["weather"][WEATHER_FIELDS[0]]["available_at"] = "2020-06-02T00:00:00Z"
    elif mutation == "future_scene":
        rows[0]["scene_available_at"] = "2020-06-02T00:00:00Z"
    elif mutation == "event_overlap":
        rows[2]["event_group"] = rows[0]["event_group"]
    elif mutation == "region_overlap":
        rows[2]["region_id"] = rows[0]["region_id"]
    elif mutation == "scene_overlap":
        rows[2]["scene_id"] = rows[0]["scene_id"]
    elif mutation == "nrt":
        rows[0]["label_source_quality"] = "NRT"
    elif mutation == "unknown_coverage":
        rows[0]["label_coverage_verified"] = False
    elif mutation == "wrong_horizon":
        rows[0]["label_window_end"] = "2020-06-09T12:00:00Z"
    elif mutation == "overlapping_geography":
        rows[2]["geometry"] = rows[0]["geometry"]
    elif mutation == "temporal_overlap":
        for row in rows[2:4]:
            row["prediction_at"] = "2020-06-05T12:00:00Z"
            row["label_window_end"] = "2020-06-12T12:00:00Z"
            row["scene_acquired_at"] = row["scene_available_at"] = "2020-06-05T09:00:00Z"
            for value in row["weather"].values():
                value["observed_at"] = value["available_at"] = "2020-06-05T09:00:00Z"
    with pytest.raises(ValueError):
        validate_fire_records(rows)
