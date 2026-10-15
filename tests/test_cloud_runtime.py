"""Cloud contract tests; real checkpoint parity remains separately artifact-gated."""

from pathlib import Path

import pytest

from ecosentinel.cloud_rpc import validate_identity
from ecosentinel.common import DataUnavailable, read_json, write_json
from ecosentinel.onnx_runtime import load_onnx


def test_cloud_paths_reject_cross_session_or_traversal():
    with pytest.raises(ValueError):
        validate_identity({"session": "../owner", "id": "1", "owner": "2"})


def test_exported_model_checks_provenance_before_loading(tmp_path):
    candidate = Path("apps/backend/models/habitat-7729")
    if not (candidate / "onnx.json").exists():
        pytest.skip("Authentic converted model not installed")
    for name in ["config.json", "metrics.json", "onnx.json"]:
        (tmp_path / name).write_bytes((candidate / name).read_bytes())
    proof = read_json(tmp_path / "onnx.json")
    proof["source_checkpoint_sha256"] = "0" * 64
    write_json(tmp_path / "onnx.json", proof)
    with pytest.raises(DataUnavailable, match="provenance"):
        load_onnx(tmp_path)
