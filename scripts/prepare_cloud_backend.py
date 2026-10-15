"""Bundle only verified inference artifacts and runtime source, never training data or credentials."""

import shutil

from ecosentinel.common import ROOT
from ecosentinel.onnx_runtime import load_onnx

destination = ROOT / "apps/backend"
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
    shutil.copyfile(ROOT / "ecosentinel" / name, source / name)
model = destination / "models/habitat-7729"
load_onnx(model)
installed = destination / "runtime/models/habitat-7729"
installed.mkdir(parents=True, exist_ok=True)
for name in ["model.onnx", "config.json", "metrics.json", "onnx.json"]:
    shutil.copyfile(model / name, installed / name)
print("Bundled verified primary trained model and bounded compute stages")
