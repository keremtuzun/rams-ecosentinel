"""CPU execution of the actual trained network; conversion provenance is mandatory."""

from pathlib import Path

import numpy as np

from ecosentinel.common import PREPROCESSING, DataUnavailable, read_json, sha256


class OnnxModel:
    def __init__(self, path):
        import onnxruntime as ort

        settings = ort.SessionOptions()
        settings.intra_op_num_threads = 1
        settings.inter_op_num_threads = 1
        settings.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
        self.session = ort.InferenceSession(
            str(path), sess_options=settings, providers=["CPUExecutionProvider"]
        )

    def predict(self, before, after):
        return self.session.run(["score"], {"before": before, "after": after})[0]


def load_onnx(directory):
    directory = Path(directory)
    config, metrics = read_json(directory / "config.json"), read_json(directory / "metrics.json")
    proof = read_json(directory / "onnx.json")
    if not metrics["weights_changed"] or metrics["parameter_l1_change"] <= 0:
        raise DataUnavailable("Model lacks evidence of gradient training")
    if (
        config["preprocessing"] != PREPROCESSING
        or proof["source_checkpoint_sha256"] != metrics["checkpoint_sha256"]
    ):
        raise DataUnavailable("ONNX model source/preprocessing provenance mismatch")
    if proof["onnx_sha256"] != sha256(directory / "model.onnx"):
        raise DataUnavailable("ONNX artifact checksum mismatch")
    if (
        proof["mask_disagreements"] != 0
        or proof["max_abs_error"] > 1e-4
        or proof["verified_regions"] != ["marmaris", "milas", "manavgat", "izmir"]
    ):
        raise DataUnavailable("ONNX parity verification gate failed")
    return OnnxModel(directory / "model.onnx"), config, metrics


def tiled_onnx_scores(model, before, after, valid, tile=64, bands="multispectral", temporal=True):
    h, w = valid.shape
    pad_h, pad_w = (-h) % tile, (-w) % tile
    a, b = [np.clip(x, -0.1, 1.2).astype(np.float32) / 0.3 for x in [before, after]]
    a[:, ~valid], b[:, ~valid] = 0, 0
    if bands == "rgb":
        a, b = a[:3], b[:3]
    if not temporal:
        a = b.copy()
    a, b = [np.pad(x, [(0, 0), (0, pad_h), (0, pad_w)]) for x in [a, b]]
    result = np.zeros((h + pad_h, w + pad_w), np.float32)
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            result[y : y + tile, x : x + tile] = model.predict(
                a[None, :, y : y + tile, x : x + tile], b[None, :, y : y + tile, x : x + tile]
            )[0]
    return result[:h, :w]
