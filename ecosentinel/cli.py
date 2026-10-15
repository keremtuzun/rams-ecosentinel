import argparse
import json
import logging
from pathlib import Path

from ecosentinel.common import ARTIFACTS, ROOT


def main():
    parser = argparse.ArgumentParser(prog="ecosentinel")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    context = commands.add_parser("worldcover-context")
    context.add_argument("region", type=Path)
    acquire = commands.add_parser("acquire")
    acquire.add_argument("--regions", type=Path, default=ROOT / "scripts" / "study_regions.json")
    acquire.add_argument("--output", type=Path, default=ARTIFACTS / "dataset")
    train = commands.add_parser("train-habitat")
    train.add_argument("--dataset", type=Path, default=ARTIFACTS / "dataset")
    train.add_argument("--output", type=Path)
    train.add_argument("--epochs", type=int, default=40)
    train.add_argument("--patience", type=int, default=8)
    train.add_argument("--seed", type=int, default=7729)
    train.add_argument("--resume", type=Path)
    train.add_argument("--bands", choices=["rgb", "multispectral"], default="multispectral")
    train.add_argument("--single-date", action="store_true")
    train.add_argument("--skip-baselines", action="store_true")
    fire = commands.add_parser("train-fire")
    fire.add_argument("manifest", type=Path)
    fire.add_argument("--output", type=Path, required=True)
    fire.add_argument("--epochs", type=int, default=60)
    labels = commands.add_parser("build-fire-labels")
    labels.add_argument("features", type=Path)
    labels.add_argument("observations", type=Path)
    labels.add_argument("coverage", type=Path)
    labels.add_argument("--output", type=Path, required=True)
    inference = commands.add_parser("infer-offline")
    inference.add_argument("region", type=Path)
    inference.add_argument("--output", type=Path, required=True)
    inference.add_argument("--model", type=Path)
    publish = commands.add_parser("import-result")
    publish.add_argument("result", type=Path)
    commands.add_parser("migrate")
    worker = commands.add_parser("worker")
    worker.add_argument("--once", action="store_true")
    process = commands.add_parser("process-job")
    process.add_argument("job_id")
    process.add_argument("owner")
    registry = commands.add_parser("registry")
    registry.add_argument("--output", type=Path, default=ARTIFACTS / "registry.json")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.command == "doctor":
        import os
        import platform
        import shutil
        import torch

        print(
            json.dumps(
                {
                    "python": platform.python_version(),
                    "torch": torch.__version__,
                    "cuda": torch.cuda.is_available(),
                    "logical_cpus": os.cpu_count(),
                    "free_disk_gb": round(shutil.disk_usage(ROOT).free / 1e9, 2),
                    "credentials_present": {
                        key: bool(os.environ.get(key)) for key in ["FIRMS_MAP_KEY", "CDSAPI_KEY"]
                    },
                },
                indent=2,
            )
        )
    elif args.command == "worldcover-context":
        import numpy as np
        from shapely.geometry import shape
        from ecosentinel.common import read_json, write_json, sha256, utcnow
        from ecosentinel.raster import Grid, read_aligned, write_raster
        from ecosentinel.sources import worldcover_url

        meta = read_json(args.region / "sample.json")
        lon, lat = shape(meta["geometry"]).centroid.coords[0]
        url = worldcover_url(lon, lat)
        grid = Grid.from_metadata(meta["grid"])
        context = read_aligned(url, grid, True)
        write_raster(
            args.region / "worldcover2021.tif",
            np.where(np.isfinite(context), context, 0).astype(np.uint8)[None],
            grid,
            nodata=0,
        )
        write_json(
            args.region / "worldcover2021.json",
            {
                "source_url": url,
                "retrieved_at": utcnow(),
                "sha256": sha256(args.region / "worldcover2021.tif"),
                "license": "CC BY 4.0",
                "meaning": "2021 v200 land-cover context, not a change label",
                "grid": grid.metadata(),
            },
        )
    elif args.command == "acquire":
        from ecosentinel.dataset import acquire_dataset

        acquire_dataset(args.regions, args.output)
    elif args.command == "train-habitat":
        from ecosentinel.training import train_habitat

        train_habitat(
            args.dataset,
            args.output,
            args.epochs,
            args.patience,
            args.seed,
            args.resume,
            args.bands,
            not args.single_date,
            not args.skip_baselines,
        )
    elif args.command == "train-fire":
        from ecosentinel.fire import train_fire

        train_fire(args.manifest, args.output, args.epochs)
    elif args.command == "build-fire-labels":
        from ecosentinel.fire import build_fire_labels

        build_fire_labels(args.features, args.observations, args.coverage, args.output)
    elif args.command == "infer-offline":
        from ecosentinel.inference import infer_offline

        infer_offline(args.region, args.output, args.model)
    elif args.command == "import-result":
        from ecosentinel.common import read_json
        from ecosentinel.jobs import Queue

        report = read_json(args.result / "report.json")
        before, after = report["source_observations"]
        request = {
            "geometry": report["geometry"],
            "before_start": before["query"]["start"],
            "before_end": before["query"]["end"],
            "after_start": after["query"]["start"],
            "after_end": after["query"]["end"],
            "module": "habitat",
        }
        queue = Queue()
        queue.migrate()
        print(queue.import_result(request, args.result))
    elif args.command == "migrate":
        from ecosentinel.jobs import Queue

        Queue().migrate()
    elif args.command == "worker":
        from ecosentinel.worker import run_worker

        run_worker(args.once)
    elif args.command == "process-job":
        from ecosentinel.worker import process_one

        process_one(args.job_id, args.owner)
    elif args.command == "registry":
        from ecosentinel.common import read_json, sha256, utcnow, write_json

        files = []
        for path in sorted(ARTIFACTS.rglob("*")):
            if (
                path.is_file()
                and path.suffix in {".pt", ".json", ".tif", ".npz", ".csv", ".pdf", ".png", ".jpg"}
                and path != args.output
            ):
                files.append(
                    {
                        "path": path.relative_to(ARTIFACTS).as_posix(),
                        "bytes": path.stat().st_size,
                        "sha256": sha256(path),
                    }
                )
        write_json(
            args.output,
            {
                "generated_at": utcnow(),
                "files": files,
                "dataset": read_json(ARTIFACTS / "dataset" / "manifest.json")
                if (ARTIFACTS / "dataset" / "manifest.json").exists()
                else None,
            },
        )


if __name__ == "__main__":
    main()
