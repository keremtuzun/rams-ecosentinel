"""Export verified task-trained checkpoints and gate the complete four-region parity."""

import shutil
import argparse

import numpy as np
import torch
from torch import nn

from ecosentinel.common import ARTIFACTS, ROOT, sha256, utcnow, write_json
from ecosentinel.inference import load_model
from ecosentinel.onnx_runtime import OnnxModel, tiled_onnx_scores
from ecosentinel.training import tiled_scores


class Scores(nn.Module):
    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, before, after):
        return self.model(before, after).sigmoid()


destination = ROOT / "apps/backend/models"
parser = argparse.ArgumentParser()
parser.add_argument("--model", choices=["habitat-7729", "habitat-7730"], default="habitat-7729")
for name in [parser.parse_args().model]:
    original = ARTIFACTS / "models" / name
    model, config, metrics = load_model(original)
    target = destination / name
    target.mkdir(parents=True, exist_ok=True)
    for filename in ["config.json", "metrics.json"]:
        shutil.copyfile(original / filename, target / filename)
    torch.onnx.export(
        Scores(model).eval(),
        (torch.zeros(1, 6, 64, 64), torch.zeros(1, 6, 64, 64)),
        target / "model.onnx",
        input_names=["before", "after"],
        output_names=["score"],
        opset_version=17,
        dynamo=False,
    )
    exported = OnnxModel(target / "model.onnx")
    errors, disagreements = [], 0
    for region in ["marmaris", "milas", "manavgat", "izmir"]:
        with np.load(ARTIFACTS / "dataset" / region / "sample.npz") as data:
            with torch.inference_mode():
                reference = tiled_scores(model, data["before"], data["after"], data["observation_valid"])
            converted = tiled_onnx_scores(exported, data["before"], data["after"], data["observation_valid"])
            errors.append(float(np.max(np.abs(reference - converted))))
            disagreements += int(
                np.count_nonzero((reference >= config["threshold"]) != (converted >= config["threshold"]))
            )
    if max(errors) > 1e-4 or disagreements:
        raise ValueError(f"Conversion parity failed: {max(errors)=}, {disagreements=}")
    write_json(
        target / "onnx.json",
        {
            "created_at": utcnow(),
            "source_checkpoint_sha256": metrics["checkpoint_sha256"],
            "onnx_sha256": sha256(target / "model.onnx"),
            "max_abs_error": max(errors),
            "mask_disagreements": disagreements,
            "verified_regions": ["marmaris", "milas", "manavgat", "izmir"],
            "tile": 64,
        },
    )
    print(f"{name}: max error {max(errors):.8f}; mask disagreements {disagreements}")
