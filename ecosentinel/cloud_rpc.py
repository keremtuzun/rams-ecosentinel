"""Bounded compute stages. Persistent coordination lives in the web service, not /tmp."""

import hashlib
import io
import json
import re
import sys
import tempfile
from pathlib import Path
from uuid import UUID

import numpy as np

from ecosentinel.common import DataUnavailable, read_json, write_json
from ecosentinel.geometry import AnalysisRequest
from ecosentinel.raster import acquire_scene, joint_valid_mask, make_grid
from ecosentinel.sources import search_sentinel


def validate_identity(payload):
    session, job_id, owner = [payload.get(k, "") for k in ["session", "id", "owner"]]
    if not re.fullmatch(r"[0-9a-f]{32}", session) or str(UUID(job_id)) != job_id or str(UUID(owner)) != owner:
        raise ValueError("Invalid processing identity")
    return f"analysis/{session}/{job_id}/{owner}"


def put_file(path, prefix):
    from vercel import blob

    content = Path(path).read_bytes()
    key = prefix + "/" + Path(path).name
    blob.put(key, content, access="private", overwrite=False, multipart=len(content) > 4_000_000)
    return {"path": key, "sha256": hashlib.sha256(content).hexdigest(), "size": len(content)}


def read_reference(reference, session, job_id):
    from vercel import blob

    path = reference["path"]
    if not path.startswith(f"analysis/{session}/{job_id}/") or ".." in path or len(path.split("/")) != 5:
        raise ValueError("Invalid intermediate artifact reference")
    if not 0 < reference["size"] <= 100_000_000:
        raise DataUnavailable("Intermediate observation exceeds the bounded 50 km input limit")
    result = blob.get(path, access="private", use_cache=False)
    if result is None or result.status_code != 200 or len(result.content) > 100_000_000:
        raise DataUnavailable("Intermediate observation is unavailable")
    if hashlib.sha256(result.content).hexdigest() != reference["sha256"]:
        raise DataUnavailable("Intermediate observation checksum mismatch")
    return result.content


def run(payload):
    request = AnalysisRequest.model_validate(payload["request"])
    if request.module != "habitat":
        raise DataUnavailable("Wildfire forecasting unavailable")
    action = payload["action"]
    if action == "validate":
        make_grid(request.geometry)
        return {"request": request.model_dump(mode="json")}
    if action == "scenes":
        result = {}
        for name, start, end in [
            ("before", request.before_start, request.before_end),
            ("after", request.after_start, request.after_end),
        ]:
            result[name] = [
                {"id": item["id"], "acquired_at": item["properties"]["datetime"]}
                for item in search_sentinel(request.geometry, start, end)[:30]
            ]
        return result
    if action not in ["before", "after", "infer"]:
        raise ValueError("Unsupported compute stage")
    prefix = validate_identity(payload)
    grid = make_grid(request.geometry)
    with tempfile.TemporaryDirectory(prefix="ecosentinel-") as temporary:
        output = Path(temporary)
        if action in ["before", "after"]:
            start, end = (
                (request.before_start, request.before_end)
                if action == "before"
                else (request.after_start, request.after_end)
            )
            data, valid, meta = acquire_scene(request.geometry, start, end, grid, output)
            np.savez_compressed(output / "observation.npz", data=data, valid=valid)
            write_json(output / "observation.json", meta)
            return {
                "data": put_file(output / "observation.npz", prefix),
                "metadata": put_file(output / "observation.json", prefix),
                "source_index": put_file(output / "source_index.tif", prefix),
            }
        before, after = [], []
        metas = []
        for name, destination in [("before", before), ("after", after)]:
            reference = payload["observations"][name]
            data = read_reference(reference["data"], payload["session"], payload["id"])
            meta = json.loads(read_reference(reference["metadata"], payload["session"], payload["id"]))
            if meta["grid"] != grid.metadata():
                raise DataUnavailable("Intermediate grid differs from the requested area")
            with np.load(io.BytesIO(data), allow_pickle=False) as arrays:
                destination.extend([arrays["data"], arrays["valid"].astype(bool)])
            metas.append(meta)
            if "source_index" in reference:
                source_map = read_reference(reference["source_index"], payload["session"], payload["id"])
                if hashlib.sha256(source_map).hexdigest() != meta["checksums"]["source_index.tif"]:
                    raise DataUnavailable("Source assignment checksum mismatch")
                (output / f"source_{name}_index.tif").write_bytes(source_map)
        valid = joint_valid_mask(before[1], after[1], request.geometry, grid)
        from ecosentinel.inference import infer_pair
        from ecosentinel.exports import report_csv, report_pdf
        from ecosentinel.common import ARTIFACTS

        report = infer_pair(before[0], after[0], valid, grid, *metas, output, geometry=request.geometry)
        report["onnx_conversion"] = read_json(ARTIFACTS / "models/habitat-7729/onnx.json")
        write_json(output / "report.json", report)
        (output / "assessment.csv").write_text(report_csv(report), encoding="utf-8")
        (output / "assessment.pdf").write_bytes(report_pdf(report, output))
        files = {}
        for name in [
            "before.png",
            "after.png",
            "overlay.png",
            "map.png",
            "score.tif",
            "mask.tif",
            "indices.tif",
            "source_before_index.tif",
            "source_after_index.tif",
            "uncertainty.tif",
            "change.geojson",
            "report.json",
            "assessment.pdf",
            "assessment.csv",
        ]:
            if (output / name).is_file():
                files[name] = put_file(output / name, prefix)
        return {"report": report, "files": files}


if __name__ == "__main__":
    try:
        raw = sys.stdin.buffer.read(16385)
        if len(raw) > 16384:
            raise ValueError("Request exceeds 16 KB")
        result = run(json.loads(raw))
        print(json.dumps({"ok": True, "result": result}, allow_nan=False))
    except (DataUnavailable, ValueError) as exc:
        print(json.dumps({"ok": False, "detail": str(exc)}))
    except Exception as exc:
        print(json.dumps({"ok": False, "detail": "Cloud processing failed", "type": type(exc).__name__}))
