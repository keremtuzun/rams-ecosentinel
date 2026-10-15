"""Plot actual source observations, reference and eligibility for dataset review."""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from ecosentinel.common import ARTIFACTS, read_json
from ecosentinel.raster import indices

manifest = read_json(ARTIFACTS / "dataset" / "manifest.json")
fig, axes = plt.subplots(4, 4, figsize=(15, 15))
for row, region in enumerate(manifest["regions"]):
    with np.load(ARTIFACTS / "dataset" / region["sample"]) as sample:
        for col, key in enumerate(["before", "after"]):
            rgb = np.moveaxis(np.clip(sample[key][[2, 1, 0]] / 0.3, 0, 1) ** (1 / 1.5), 0, -1)
            axes[row, col].imshow(rgb)
            source = region[f"{key}_scene"]
            axes[row, col].set_title(f"{region['id']} {key}\n{source['acquired_at'][:10]}", fontsize=10)
        axes[row, 2].imshow(np.where(sample["valid"], sample["label"], np.nan), vmin=0, vmax=1, cmap="YlOrRd")
        axes[row, 2].set_title(
            f"Annual loss reference {region['loss_year']}\nmasked outside eligible forest", fontsize=10
        )
        delta = indices(sample["after"])["nbr"] - indices(sample["before"])["nbr"]
        axes[row, 3].imshow(
            np.where(sample["observation_valid"], delta, np.nan), vmin=-0.7, vmax=0.7, cmap="RdYlGn"
        )
        axes[row, 3].set_title("Delta NBR (after − before)\nnot a degradation assertion", fontsize=10)
for ax in axes.flat:
    ax.axis("off")
fig.suptitle(
    "RAMS EcoSentinel · acquired Sentinel-2 observations and algorithmic reference labels", fontsize=14
)
fig.tight_layout()
fig.savefig(ARTIFACTS / "dataset" / "visual_qa.png", dpi=120)
plt.close(fig)
