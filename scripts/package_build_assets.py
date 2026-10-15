"""Create immutable bundles from already verified local artifacts, without any credentials."""

import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def package(kind, source, paths):
    entries = [
        {"path": name, "data": base64.b64encode((source / name).read_bytes()).decode("ascii")}
        for name in sorted(paths)
    ]
    raw = json.dumps(
        {"format": "ecosentinel-build-assets-v1", "files": entries}, separators=(",", ":")
    ).encode()
    data = gzip.compress(raw, mtime=0)
    digest = hashlib.sha256(data).hexdigest()
    target = ROOT / "artifacts/deployment" / f"{kind}-build-assets.json.gz"
    target.write_bytes(data)
    return {
        "local_file": str(target),
        "path": f"build-assets/{kind}/{digest}.json.gz",
        "sha256": digest,
        "files": len(entries),
        "bytes": len(data),
    }


def main():
    evidence = ROOT / "apps/web/public/evidence"
    manifest = json.loads((evidence / "checksums.json").read_text())
    for name, digest in manifest.items():
        if hashlib.sha256((evidence / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Evidence checksum mismatch")
    model = ROOT / "apps/backend/models/habitat-7729"
    from ecosentinel.onnx_runtime import load_onnx

    load_onnx(model)
    bundles = {
        "web": package("web", evidence, [*manifest, "checksums.json"]),
        "backend": package("backend", model, ["model.onnx", "config.json", "metrics.json", "onnx.json"]),
    }
    (ROOT / "artifacts/deployment/build-assets.json").write_text(json.dumps(bundles, indent=2))
    print(json.dumps(bundles, indent=2))


if __name__ == "__main__":
    main()
