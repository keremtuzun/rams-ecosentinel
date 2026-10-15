import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss, confusion_matrix, roc_auc_score


def binary_metrics(target, score, threshold=0.5):
    target, score = np.asarray(target).reshape(-1), np.asarray(score).reshape(-1)
    if not target.size or target.shape != score.shape or not np.isfinite(score).all():
        raise ValueError("Metrics require nonempty, aligned finite observations")
    if not np.isin(target, [0, 1]).all() or ((score < 0) | (score > 1)).any():
        raise ValueError("Invalid target or score range")
    tn, fp, fn, tp = confusion_matrix(target, score >= threshold, labels=[0, 1]).ravel()
    precision, recall = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
    calibration = 0.0
    for low in np.arange(0, 1, 0.1):
        mask = (score >= low) & (score < low + 0.1 if low < 0.9 else score <= 1)
        if mask.any():
            calibration += mask.mean() * abs(score[mask].mean() - target[mask].mean())
    return {
        "pixels_or_examples": int(target.size),
        "positives": int(target.sum()),
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(2 * precision * recall / max(precision + recall, 1e-12)),
        "iou": float(tp / max(tp + fp + fn, 1)),
        "accuracy": float((tp + tn) / target.size),
        "pr_auc": float(average_precision_score(target, score)) if target.sum() else None,
        "roc_auc": float(roc_auc_score(target, score)) if len(np.unique(target)) == 2 else None,
        "brier_score": float(brier_score_loss(target, score)),
        "ece_10_bins": float(calibration),
        "false_positive_rate": float(fp / max(fp + tn, 1)),
        "confusion_matrix": [[int(tn), int(fp)], [int(fn), int(tp)]],
        "mapped_pixel_count_difference": int(tp + fp - target.sum()),
        "threshold": float(threshold),
        "score_meaning": "uncalibrated classifier score; not an ecological probability",
    }
