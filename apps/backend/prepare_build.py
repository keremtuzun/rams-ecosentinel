"""Restore pinned private model assets and bundle the repository's current compute source."""

import base64
import gzip
import hashlib
import io
import json
import os
import re
import shutil
from pathlib import Path

MODEL_FILES = {"model.onnx", "config.json", "metrics.json", "onnx.json"}


def decode_model(data, digest):
    if not re.fullmatch(r"[a-f0-9]{64}", digest) or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("Build asset checksum mismatch")
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as zipped:
        raw = zipped.read(5_000_001)
    if len(raw) > 5_000_000:
        raise ValueError("Build asset bundle too large")
    bundle = json.loads(raw)
    if bundle.get("format") != "ecosentinel-build-assets-v1":
        raise ValueError("Invalid build asset bundle")
    files = {}
    for entry in bundle["files"]:
        if entry["path"] not in MODEL_FILES or entry["path"] in files:
            raise ValueError("Invalid model asset path")
        files[entry["path"]] = base64.b64decode(entry["data"], validate=True)
    if set(files) != MODEL_FILES:
        raise ValueError("Incomplete trained model bundle")
    conversion = json.loads(files["onnx.json"])
    metrics = json.loads(files["metrics.json"])
    if (
        hashlib.sha256(files["model.onnx"]).hexdigest() != conversion["onnx_sha256"]
        or metrics["checkpoint_sha256"] != conversion["source_checkpoint_sha256"]
    ):
        raise ValueError("Trained model provenance mismatch")
    return files


def main():
    destination = Path(__file__).resolve().parent
    root = destination.parents[1]
    source = destination / "ecosentinel"
    source.mkdir(exist_ok=True)
    for name in [
        "__init__.py",
        "common.py",
        "geometry.py",
        "raster.py",
        "sources.py",
        "inference.py",
        "onnx_runtime.py",
        "cloud_rpc.py",
        "exports.py",
    ]:
        shutil.copyfile(root / "ecosentinel" / name, source / name)
    path = os.environ.get("ECOSENTINEL_BUILD_ASSET_PATH", "")
    digest = os.environ.get("ECOSENTINEL_BUILD_ASSET_SHA256", "")
    if not path and not digest and not os.environ.get("VERCEL"):
        print("Local build: using the locally installed trained model")
        return
    if not re.fullmatch(r"build-assets/backend/[a-f0-9]{64}\.json\.gz", path):
        raise ValueError("Pinned private model assets are not configured")
    from vercel import blob

    result = blob.get(path, access="private", use_cache=False)
    if result is None or result.status_code != 200 or len(result.content) > 5_000_000:
        raise ValueError("Private model assets are unavailable")
    files = decode_model(result.content, digest)
    model = destination / "runtime/models/habitat-7729"
    model.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (model / name).write_bytes(content)
    from ecosentinel.onnx_runtime import load_onnx

    load_onnx(model)
    print("Bundled current compute source and verified trained model")


if __name__ == "__main__":
    main()
