import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = Path(os.environ.get("ECOSENTINEL_ARTIFACTS", str(ROOT / "artifacts"))).resolve()
PREPROCESSING = {
    "version": "s2-l2a-30m-v1",
    "bands": ["blue", "green", "red", "nir", "swir16", "swir22"],
    "resolution_m": 30,
    "resampling": "bilinear reflectance; nearest SCL and labels",
    "valid_scl": [4, 5],
    "cloud_buffer_pixels": 2,
    "reflectance_bounds": [-0.1, 1.2],
    "network_scale": "clip(-0.1,1.2)/0.3; invalid pixels zero",
}


class DataUnavailable(RuntimeError):
    """A required real observation or verified artifact is unavailable."""


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
