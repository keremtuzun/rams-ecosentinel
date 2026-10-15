"""Optional local integration tests on actual acquired and trained artifacts.

CI skips these if the ignored real dataset/checkpoint artifacts are absent. No fake fixture
can replace their evidence. Baseline software tests run separately in CI.
"""

import shutil

import numpy as np
import pytest
from fastapi.testclient import TestClient

from ecosentinel.api import create_app
from ecosentinel.common import ARTIFACTS, DataUnavailable, read_json, write_json
from ecosentinel.dataset import verify_manifest
from ecosentinel.inference import load_model
from ecosentinel.jobs import Queue

REAL = (ARTIFACTS / "models" / "habitat-7729" / "metrics.json").exists()
pytestmark = pytest.mark.skipif(not REAL, reason="Real dataset and trained checkpoint not installed")


def test_actual_provenance_and_trained_checkpoint():
    manifest = verify_manifest(ARTIFACTS / "dataset")
    _, config, metrics = load_model()
    assert metrics["epochs_run"] > 1 and metrics["weights_changed"]
    assert metrics["parameter_l1_change"] > 0
    assert {r["split"] for r in manifest["regions"]} == {"train", "validation", "test"}
    assert config["initialization"].startswith("random")
    assert metrics["test"]["aggregate"]["positives"] > 0


def test_checkpoint_tamper_is_rejected(tmp_path):
    source = ARTIFACTS / "models" / "habitat-7729"
    for name in ["best.pt", "config.json", "metrics.json"]:
        shutil.copyfile(source / name, tmp_path / name)
    with (tmp_path / "best.pt").open("ab") as file:
        file.write(b"tamper")
    with pytest.raises(DataUnavailable, match="checksum"):
        load_model(tmp_path)


def test_preprocessing_tamper_is_rejected(tmp_path):
    source = ARTIFACTS / "models" / "habitat-7729"
    for name in ["best.pt", "config.json", "metrics.json"]:
        shutil.copyfile(source / name, tmp_path / name)
    config = read_json(tmp_path / "config.json")
    config["preprocessing"]["bands"] = list(reversed(config["preprocessing"]["bands"]))
    write_json(tmp_path / "config.json", config)
    with pytest.raises(DataUnavailable, match="preprocessing"):
        load_model(tmp_path)


def test_resume_without_improvement_preserves_selected_checkpoint_config(tmp_path):
    import torch
    from ecosentinel.training import train_habitat

    source = ARTIFACTS / "models" / "habitat-7729"
    for name in ["best.pt", "last.pt", "config.json", "metrics.json"]:
        shutil.copyfile(source / name, tmp_path / name)
    checkpoint = torch.load(tmp_path / "last.pt", weights_only=True)
    # Test-only control forces no new best, reproducing the configuration-mismatch failure.
    checkpoint["best_loss"] = -1.0
    torch.save(checkpoint, tmp_path / "last.pt")
    selected_hash = read_json(source / "metrics.json")["checkpoint_sha256"]
    result = train_habitat(
        ARTIFACTS / "dataset",
        tmp_path,
        epochs=checkpoint["epoch"] + 2,
        patience=12,
        seed=7729,
        resume=tmp_path / "last.pt",
        baselines=False,
    )
    assert result["checkpoint_sha256"] == selected_hash
    assert result["epochs_run"] == len(checkpoint["history"]) + 1
    _, config, _ = load_model(tmp_path)
    assert config == torch.load(tmp_path / "best.pt", weights_only=True)["config"]


def test_actual_exports_and_pixel_inspection(tmp_path):
    results = ARTIFACTS / "results" / "izmir-heldout"
    if not results.exists():
        pytest.skip("Held-out inference result is not installed")
    queue = Queue(f"sqlite:///{(tmp_path / 'jobs.db').as_posix()}")
    queue.migrate()
    request = {"geometry": read_json(results / "report.json")["geometry"], "module": "habitat"}
    job_id = queue.import_result(request, results)
    try:
        with TestClient(create_app(queue)) as client:
            for format, media in [
                ("pdf", "application/pdf"),
                ("csv", "text/csv"),
                ("geojson", "application/geo+json"),
            ]:
                response = client.get(f"/api/jobs/{job_id}/export/{format}")
                assert response.status_code == 200 and media in response.headers["content-type"]
                assert len(response.content) > 200
                if format == "pdf":
                    assert response.content.startswith(b"%PDF")
            response = client.get(f"/api/jobs/{job_id}/inspect?longitude=27.02&latitude=38.20")
            assert response.status_code == 200
            score = response.json()["score"]
            assert score is None or np.isfinite(score) and 0 <= score <= 1
            assert client.get(f"/api/jobs/{job_id}/inspect?longitude=30&latitude=40").status_code == 422
    finally:
        # Remove only this temporary test's imported result, after exact path containment verification.
        result_path = (ARTIFACTS / "jobs" / job_id).resolve()
        assert result_path.parent == (ARTIFACTS / "jobs").resolve()
        shutil.rmtree(result_path)
