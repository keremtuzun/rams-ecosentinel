"""Build bootstrap integrity fixtures; no fixture is installed as a real model."""

import base64
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("backend_build", Path("apps/backend/prepare_build.py"))
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def bundle(unsafe=False, bad_provenance=False):
    model = b"test-only model bytes"
    conversion = {"onnx_sha256": hashlib.sha256(model).hexdigest(), "source_checkpoint_sha256": "a" * 64}
    metrics = {"checkpoint_sha256": ("b" if bad_provenance else "a") * 64}
    files = {
        "model.onnx": model,
        "config.json": b"{}",
        "onnx.json": json.dumps(conversion).encode(),
        "metrics.json": json.dumps(metrics).encode(),
    }
    if unsafe:
        files["../.env"] = b"fixture"
    data = gzip.compress(
        json.dumps(
            {
                "format": "ecosentinel-build-assets-v1",
                "files": [
                    {"path": path, "data": base64.b64encode(content).decode()}
                    for path, content in files.items()
                ],
            }
        ).encode()
    )
    return data, hashlib.sha256(data).hexdigest()


def test_model_bundle_is_pinned_and_never_extracts_arbitrary_paths():
    data, digest = bundle()
    assert set(build.decode_model(data, digest)) == build.MODEL_FILES
    with pytest.raises(ValueError, match="checksum mismatch"):
        build.decode_model(data, "0" * 64)
    data, digest = bundle(unsafe=True)
    with pytest.raises(ValueError, match="Invalid model asset path"):
        build.decode_model(data, digest)


def test_build_rejects_model_provenance_mismatch():
    data, digest = bundle(bad_provenance=True)
    with pytest.raises(ValueError, match="provenance mismatch"):
        build.decode_model(data, digest)
