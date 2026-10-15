import copy
import random
import time
from pathlib import Path

import numpy as np
import torch
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from torch import nn
from torch.utils.data import DataLoader, Dataset

from ecosentinel.common import ARTIFACTS, PREPROCESSING, sha256, utcnow, write_json
from ecosentinel.dataset import verify_manifest
from ecosentinel.metrics import binary_metrics
from ecosentinel.models import SiameseUNet
from ecosentinel.raster import indices


def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(6)
    torch.use_deterministic_algorithms(True)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def network_input(bands, valid):
    output = np.clip(bands, -0.1, 1.2).astype(np.float32) / 0.3
    output[:, ~valid] = 0
    return output


class HabitatTiles(Dataset):
    def __init__(self, directory, manifest, split, tile=64, bands="multispectral", temporal=True):
        self.samples = []
        for region in manifest["regions"]:
            if region["split"] != split:
                continue
            with np.load(Path(directory) / region["sample"]) as source:
                before, after, target, valid = [source[key] for key in ["before", "after", "label", "valid"]]
                obs_valid = source["observation_valid"]
                before, after = network_input(before, obs_valid), network_input(after, obs_valid)
                if bands == "rgb":
                    before, after = before[:3], after[:3]
                if not temporal:
                    before = after.copy()
                for y in range(0, valid.shape[0] - tile + 1, tile):
                    for x in range(0, valid.shape[1] - tile + 1, tile):
                        cut = np.s_[y : y + tile, x : x + tile]
                        if valid[cut].mean() >= 0.15:
                            self.samples.append(
                                tuple(
                                    torch.from_numpy(np.array(arr, copy=True))
                                    for arr in [
                                        before[:, y : y + tile, x : x + tile],
                                        after[:, y : y + tile, x : x + tile],
                                        target[cut],
                                        valid[cut],
                                    ]
                                )
                            )
        if not self.samples:
            raise ValueError(f"No valid {split} tiles")

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, index):
        return self.samples[index]


def pixel_features(before, after, mode="all"):
    bi, ai = indices(before), indices(after)
    if mode == "delta_nbr":
        return (bi["nbr"] - ai["nbr"])[..., None]
    return np.moveaxis(
        np.concatenate(
            [before, after, after - before, np.stack([ai[k] - bi[k] for k in ["ndvi", "ndmi", "nbr"]])]
        ),
        0,
        -1,
    )


@torch.inference_mode()
def tiled_scores(model, before, after, valid, device="cpu", tile=64, bands="multispectral", temporal=True):
    model.eval()
    h, w = valid.shape
    pad_h, pad_w = (-h) % tile, (-w) % tile
    a, b = network_input(before, valid), network_input(after, valid)
    if bands == "rgb":
        a, b = a[:3], b[:3]
    if not temporal:
        a = b.copy()
    a, b = np.pad(a, [(0, 0), (0, pad_h), (0, pad_w)]), np.pad(b, [(0, 0), (0, pad_h), (0, pad_w)])
    result = np.zeros((h + pad_h, w + pad_w), np.float32)
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            ta = torch.from_numpy(a[None, :, y : y + tile, x : x + tile]).to(device)
            tb = torch.from_numpy(b[None, :, y : y + tile, x : x + tile]).to(device)
            result[y : y + tile, x : x + tile] = model(ta, tb).sigmoid()[0].cpu().numpy()
    return result[:h, :w]


def evaluation(model, directory, manifest, split, device, bands, temporal, threshold=0.5):
    regional, targets, scores = {}, [], []
    for region in manifest["regions"]:
        if region["split"] != split:
            continue
        with np.load(Path(directory) / region["sample"]) as sample:
            score = tiled_scores(
                model,
                sample["before"],
                sample["after"],
                sample["observation_valid"],
                device,
                bands=bands,
                temporal=temporal,
            )
            mask = sample["valid"].astype(bool)
            regional[region["id"]] = binary_metrics(sample["label"][mask], score[mask], threshold)
            targets.append(sample["label"][mask])
            scores.append(score[mask])
    return {
        "aggregate": binary_metrics(np.concatenate(targets), np.concatenate(scores), threshold),
        "regions": regional,
    }


def run_baselines(directory, manifest, seed):
    results = {}
    for mode in ["delta_nbr", "all"]:
        x, y = [], []
        for region in manifest["regions"]:
            if region["split"] == "train":
                with np.load(Path(directory) / region["sample"]) as sample:
                    mask = sample["valid"].astype(bool)
                    xx = pixel_features(sample["before"], sample["after"], mode)[mask]
                    yy = sample["label"][mask]
                    rng = np.random.default_rng(seed)
                    keep = rng.choice(len(yy), min(len(yy), 30000), replace=False)
                    x.append(xx[keep])
                    y.append(yy[keep])
        estimator = make_pipeline(
            StandardScaler(), LogisticRegression(max_iter=500, class_weight="balanced", random_state=seed)
        )
        estimator.fit(np.concatenate(x), np.concatenate(y))
        splits = {}
        for split in ["validation", "test"]:
            regional, targets, scores = {}, [], []
            for region in manifest["regions"]:
                if region["split"] == split:
                    with np.load(Path(directory) / region["sample"]) as sample:
                        mask = sample["valid"].astype(bool)
                        score = estimator.predict_proba(
                            pixel_features(sample["before"], sample["after"], mode)[mask]
                        )[:, 1]
                        regional[region["id"]] = binary_metrics(sample["label"][mask], score)
                        targets.append(sample["label"][mask])
                        scores.append(score)
            splits[split] = {
                "aggregate": binary_metrics(np.concatenate(targets), np.concatenate(scores)),
                "regions": regional,
            }
        # Safe numeric coefficients for reproducibility; no executable pickle artifacts.
        results[mode] = {
            "metrics": splits,
            "scaler_mean": estimator[0].mean_.tolist(),
            "scaler_scale": estimator[0].scale_.tolist(),
            "coef": estimator[1].coef_.tolist(),
            "intercept": estimator[1].intercept_.tolist(),
            "threshold": 0.5,
        }
    return results


def train_habitat(
    directory=None,
    output=None,
    epochs=40,
    patience=8,
    seed=7729,
    resume=None,
    bands="multispectral",
    temporal=True,
    baselines=True,
):
    if epochs < 1 or patience < 1:
        raise ValueError("Epoch and patience limits must be positive")
    directory = Path(directory or ARTIFACTS / "dataset")
    output = Path(output or ARTIFACTS / "models" / f"habitat-{seed}")
    if output.exists() and (output / "metrics.json").exists() and not resume:
        raise ValueError("Experiment already exists; choose a new output or explicitly resume")
    output.mkdir(parents=True, exist_ok=True)
    manifest = verify_manifest(directory)
    set_seed(seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    train = HabitatTiles(directory, manifest, "train", bands=bands, temporal=temporal)
    val = HabitatTiles(directory, manifest, "validation", bands=bands, temporal=temporal)
    generator = torch.Generator().manual_seed(seed)
    loader = DataLoader(train, batch_size=8, shuffle=True, num_workers=0, generator=generator)
    vloader = DataLoader(val, batch_size=8, shuffle=False, num_workers=0)
    model = SiameseUNet(bands=3 if bands == "rgb" else 6).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.001, weight_decay=0.001)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=3, factor=0.5)
    positive = sum(float(sample[2][sample[3]].sum()) for sample in train.samples)
    total = sum(float(sample[3].sum()) for sample in train.samples)
    if not 0 < positive < total:
        raise ValueError("Both positive and negative training labels required")
    weight = min((total - positive) / positive, 10)
    criterion = nn.BCEWithLogitsLoss(reduction="none", pos_weight=torch.tensor(weight, device=device))
    start, best_loss, stalled, history = 0, float("inf"), 0, []
    initial = copy.deepcopy(model.state_dict())
    config = {
        "architecture": "SiameseUNet",
        "width": 12,
        "bands": bands,
        "temporal": temporal,
        "initialization": "random; task-specific gradient training",
        "seed": seed,
        "epochs_max": epochs,
        "patience": patience,
        "batch_size": 8,
        "learning_rate": 0.001,
        "weight_decay": 0.001,
        "positive_weight": weight,
        "preprocessing": PREPROCESSING,
        "dataset_sha256": sha256(directory / "manifest.json"),
        "device": device,
        "threshold": 0.5,
        "threshold_policy": "predeclared 0.5; no test-set tuning",
        "tile_size": 64,
        "valid_label_pixels": int(total),
        "training_tiles": len(train),
        "validation_tiles": len(val),
        "score_meaning": "experimental uncalibrated forest-loss reference score",
        "created_at": utcnow(),
    }
    if resume:
        if not (output / "best.pt").exists():
            raise ValueError("Resume requires the original experiment directory, including best.pt")
        checkpoint = torch.load(resume, map_location=device, weights_only=True)
        for key in ["bands", "temporal", "seed", "dataset_sha256", "preprocessing"]:
            if checkpoint["config"][key] != config[key]:
                raise ValueError("Resume configuration/provenance mismatch")
        model.load_state_dict(checkpoint["model"])
        optimizer.load_state_dict(checkpoint["optimizer"])
        scheduler.load_state_dict(checkpoint["scheduler"])
        start, best_loss, history = checkpoint["epoch"] + 1, checkpoint["best_loss"], checkpoint["history"]
        stalled = checkpoint["stalled"]
        torch.set_rng_state(checkpoint["rng"])
        generator.set_state(checkpoint["loader_rng"])
        initial = checkpoint["initial"]
    write_json(output / "config.json", config)
    write_json(output / "dataset_manifest.json", manifest)
    if baselines:
        print("Training delta-NBR and multispectral logistic baselines", flush=True)
        write_json(output / "baselines.json", run_baselines(directory, manifest, seed))
    for epoch in range(start, epochs):
        began = time.monotonic()
        model.train()
        loss_sum, count = 0.0, 0
        for a, b, y, valid in loader:
            a, b, y, valid = [v.to(device) for v in [a, b, y, valid]]
            optimizer.zero_grad(set_to_none=True)
            logits = model(a, b)
            loss = criterion(logits, y)[valid].mean()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5)
            optimizer.step()
            loss_sum += float(loss.detach()) * int(valid.sum())
            count += int(valid.sum())
        model.eval()
        vsum, vcount = 0.0, 0
        with torch.inference_mode():
            for a, b, y, valid in vloader:
                a, b, y, valid = [v.to(device) for v in [a, b, y, valid]]
                loss = criterion(model(a, b), y)[valid].sum()
                vsum += float(loss)
                vcount += int(valid.sum())
        validation_loss = vsum / vcount
        scheduler.step(validation_loss)
        improved = validation_loss < best_loss - 1e-5
        if improved:
            best_loss, stalled = validation_loss, 0
        else:
            stalled += 1
        record = {
            "epoch": epoch + 1,
            "train_loss": loss_sum / count,
            "validation_loss": validation_loss,
            "learning_rate": optimizer.param_groups[0]["lr"],
            "seconds": time.monotonic() - began,
        }
        history.append(record)
        checkpoint = {
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "scheduler": scheduler.state_dict(),
            "config": config,
            "epoch": epoch,
            "best_loss": best_loss,
            "stalled": stalled,
            "history": history,
            "rng": torch.get_rng_state(),
            "loader_rng": generator.get_state(),
            "initial": initial,
        }
        torch.save(checkpoint, output / "last.pt")
        if improved:
            torch.save(checkpoint, output / "best.pt")
        write_json(output / "history.json", history)
        print(
            f"Epoch {epoch + 1}: train={record['train_loss']:.5f} val={validation_loss:.5f} ({record['seconds']:.1f}s)",
            flush=True,
        )
        if stalled >= patience:
            break
    best = torch.load(output / "best.pt", map_location=device, weights_only=True)
    model.load_state_dict(best["model"])
    # A resumed run may not improve the existing best checkpoint. Its original configuration
    # must remain paired with that selected checkpoint, including the original creation time.
    write_json(output / "config.json", best["config"])
    if resume:
        write_json(
            output / "resume.json",
            {
                "resumed_from_epoch": start,
                "requested_epoch_limit": epochs,
                "epochs_total": len(history),
                "selected_epoch": best["epoch"] + 1,
                "resumed_at": utcnow(),
            },
        )
    change = sum(float((best["model"][key].cpu() - initial[key].cpu()).abs().sum()) for key in initial)
    metrics = {
        "validation": evaluation(model, directory, manifest, "validation", device, bands, temporal),
        "test": evaluation(model, directory, manifest, "test", device, bands, temporal),
        "best_epoch": best["epoch"] + 1,
        "epochs_run": len(history),
        "parameter_l1_change": change,
        "weights_changed": change > 0,
        "checkpoint_sha256": sha256(output / "best.pt"),
        "evaluated_at": utcnow(),
        "interpretation": "Agreement with algorithmic annual forest-loss reference on eligible pixels; not independently validated habitat degradation accuracy",
        "deployment_status": "research-only; scientific deployment gate not met",
    }
    write_json(output / "metrics.json", metrics)
    plot_history(history, output / "training.png")
    return metrics


def plot_history(history, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4))
    for key in ["train_loss", "validation_loss"]:
        ax.plot([r["epoch"] for r in history], [r[key] for r in history], label=key)
    ax.set(
        xlabel="Epoch",
        ylabel="Weighted binary cross entropy",
        title="RAMS EcoSentinel · real training history",
    )
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
