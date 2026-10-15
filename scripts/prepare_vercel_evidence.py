"""Package genuine completed artifacts for a stateless hosted viewer; no predictions generated here."""

import shutil
from pathlib import Path

from ecosentinel.common import ARTIFACTS, ROOT, read_json, sha256, utcnow, write_json
from ecosentinel.exports import report_csv, report_pdf
from ecosentinel.jobs import Queue

destination = ROOT / "apps" / "web" / "public" / "evidence"
destination.mkdir(parents=True, exist_ok=True)
models = []
for directory in sorted((ARTIFACTS / "models").glob("habitat-*")):
    if (directory / "metrics.json").exists():
        metrics = read_json(directory / "metrics.json")
        if sha256(directory / "best.pt") != metrics["checkpoint_sha256"] or not metrics["weights_changed"]:
            raise ValueError("Model evidence checksum/training gate failed")
        models.append(
            {
                "id": directory.name,
                "config": read_json(directory / "config.json"),
                "metrics": metrics,
                "baselines": read_json(directory / "baselines.json")
                if (directory / "baselines.json").exists()
                else None,
            }
        )
jobs = []
for job in Queue().list():
    if job["status"] != "succeeded":
        continue
    source = ARTIFACTS / "jobs" / job["id"]
    report = read_json(source / "report.json")
    for name, digest in report["checksums"].items():
        if Path(name).name != name or sha256(source / name) != digest:
            raise ValueError("Completed result checksum/path gate failed")
    folder = destination / "jobs" / job["id"]
    folder.mkdir(parents=True, exist_ok=True)
    for name in [
        "before.png",
        "after.png",
        "overlay.png",
        "map.png",
        "score.tif",
        "mask.tif",
        "indices.tif",
        "uncertainty.tif",
        "change.geojson",
        "report.json",
    ]:
        if (source / name).is_file():
            shutil.copyfile(source / name, folder / name)
    (folder / "assessment.pdf").write_bytes(report_pdf(report, source))
    (folder / "assessment.csv").write_text(report_csv(report), encoding="utf-8")
    jobs.append({**job, "report": report})
write_json(
    destination / "catalog.json",
    {
        "packaged_at": utcnow(),
        "mode": "completed-evidence",
        "regions": read_json(ROOT / "scripts" / "study_regions.json"),
        "models": {
            "habitat": models,
            "wildfire": {
                "status": "blocked",
                "reason": "No independently evaluated prospective fire model or verified as-of covariates are installed",
            },
        },
        "jobs": jobs,
    },
)
write_json(
    destination / "checksums.json",
    {
        p.relative_to(destination).as_posix(): sha256(p)
        for p in destination.rglob("*")
        if p.is_file() and p.name != "checksums.json"
    },
)
print(f"Packaged {len(jobs)} completed real analyses and {len(models)} trained experiments")
