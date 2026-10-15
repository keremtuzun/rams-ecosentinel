Local runtime artifacts are ignored by Git. Dataset generation records source IDs, URLs,
acquisition dates, preprocessing and SHA-256 checksums. Training stores the manifest,
configuration, history, best/last checkpoints, baselines and held-out metrics.

`ecosentinel registry` writes a tracked `registry.json` describing the acquired artifacts.
The registry does not transport binaries. Reproduce them with the acquisition and training
commands in README.md, or transfer the complete artifact directory through an authorized
artifact store, then verify checksums. No external artifact store is configured.
