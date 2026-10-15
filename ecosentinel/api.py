import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from uuid import UUID

import numpy as np
import rasterio
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from ecosentinel.common import ARTIFACTS, ROOT, DataUnavailable, read_json
from ecosentinel.exports import report_csv, report_pdf
from ecosentinel.geometry import AnalysisRequest
from ecosentinel.jobs import Queue
from ecosentinel.sources import fetch_firms, search_sentinel


def create_app(queue=None):
    queue = queue or Queue()

    @asynccontextmanager
    async def lifespan(app):
        queue.migrate()
        yield

    app = FastAPI(title="RAMS EcoSentinel", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.environ.get("WEB_ORIGIN", "http://localhost:3000,http://127.0.0.1:3000").split(","),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    requests = defaultdict(deque)

    @app.middleware("http")
    async def bounds(request: Request, call_next):
        if request.method == "POST":
            length = request.headers.get("content-length")
            if length and (not length.isdigit() or int(length) > 16384):
                return JSONResponse({"detail": "Request exceeds 16 KB"}, status_code=413)
            # Streaming bound protects chunked bodies too.
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 16384:
                    return JSONResponse({"detail": "Request exceeds 16 KB"}, status_code=413)
            request._body = bytes(body)
            peer = request.client.host if request.client else "unknown"
            now = time.monotonic()
            times = requests[peer]
            while times and now - times[0] > 60:
                times.popleft()
            if len(times) >= 5:
                return JSONResponse({"detail": "Maximum five expensive requests per minute"}, status_code=429)
            times.append(now)
            if len(requests) > 1000:
                requests.clear()  # Bounded in-process local limiter; production requires gateway enforcement.
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(DataUnavailable)
    async def unavailable(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.get("/health")
    def health():
        try:
            queue.list(1)
        except Exception:
            raise HTTPException(503, "Job database is unavailable") from None
        return {"status": "ok", "service": "RAMS EcoSentinel", "mode": "research"}

    @app.get("/api/regions")
    def regions():
        return read_json(ROOT / "scripts" / "study_regions.json")

    @app.get("/api/models")
    def models():
        result = {
            "habitat": [],
            "wildfire": {
                "status": "blocked",
                "reason": "No trained and independently evaluated prospective fire model or as-of covariates are installed",
            },
        }
        for directory in sorted((ARTIFACTS / "models").glob("habitat-*")):
            if (directory / "metrics.json").exists():
                result["habitat"].append(
                    {
                        "id": directory.name,
                        "config": read_json(directory / "config.json"),
                        "metrics": read_json(directory / "metrics.json"),
                        "baselines": read_json(directory / "baselines.json")
                        if (directory / "baselines.json").exists()
                        else None,
                    }
                )
        return result

    @app.post("/api/scenes")
    def scenes(request: AnalysisRequest):
        results = {}
        for key, start, end in [
            ("before", request.before_start, request.before_end),
            ("after", request.after_start, request.after_end),
        ]:
            items = search_sentinel(request.geometry, start, end)
            results[key] = [
                {
                    "id": item["id"],
                    "acquired_at": item["properties"]["datetime"],
                    "scene_cloud_pct": item["properties"].get("eo:cloud_cover"),
                }
                for item in items[:30]
            ]
        return {
            **results,
            "note": "Catalogue matches only; local cloud and reflectance QA is performed during analysis",
        }

    @app.post("/api/jobs", status_code=202)
    def submit(request: AnalysisRequest):
        if request.module == "wildfire":
            raise DataUnavailable(
                "Wildfire forecasting unavailable: science labels and as-of weather remain incomplete"
            )
        from ecosentinel.inference import load_model

        load_model()
        job_id = queue.submit(request.model_dump(mode="json"))
        return queue.get(job_id)

    @app.get("/api/jobs")
    def list_jobs():
        return queue.list()

    def get_job(job_id):
        try:
            if str(UUID(job_id)) != job_id:
                raise ValueError()
        except ValueError:
            raise HTTPException(404, "Job not found") from None
        job = queue.get(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        return job

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        result = get_job(job_id)
        if result["status"] == "succeeded":
            result["report"] = read_json(ARTIFACTS / "jobs" / job_id / "report.json")
        return result

    def completed_path(job_id):
        record = get_job(job_id)
        if record["status"] != "succeeded":
            raise HTTPException(409, "Analysis has not succeeded")
        return ARTIFACTS / "jobs" / job_id

    @app.get("/api/jobs/{job_id}/files/{name}")
    def artifact(job_id: str, name: str):
        if name not in {
            "before.png",
            "after.png",
            "overlay.png",
            "map.png",
            "score.tif",
            "uncertainty.tif",
            "mask.tif",
            "indices.tif",
            "change.geojson",
            "report.json",
        }:
            raise HTTPException(404, "Artifact not found")
        path = completed_path(job_id) / name
        if not path.is_file():
            raise HTTPException(404, "Artifact not found")
        return FileResponse(path, filename=name if name.endswith(".tif") else None)

    @app.get("/api/jobs/{job_id}/export/{format}")
    def export(job_id: str, format: str):
        path = completed_path(job_id)
        report = read_json(path / "report.json")
        if format == "geojson":
            return FileResponse(
                path / "change.geojson", media_type="application/geo+json", filename=f"{job_id}.geojson"
            )
        if format == "csv":
            return Response(
                report_csv(report),
                media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="{job_id}.csv"'},
            )
        if format == "pdf":
            return Response(
                report_pdf(report, path),
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{job_id}.pdf"'},
            )
        if format == "json":
            return FileResponse(
                path / "report.json", media_type="application/json", filename=f"{job_id}.json"
            )
        raise HTTPException(404, "Supported exports: PDF, CSV, GeoJSON, JSON")

    @app.get("/api/jobs/{job_id}/inspect")
    def inspect(job_id: str, longitude: float, latitude: float):
        if not np.isfinite([longitude, latitude]).all():
            raise HTTPException(422, "Coordinates must be finite")
        path = completed_path(job_id)
        with rasterio.open(path / "score.tif") as source:
            from pyproj import Transformer

            x, y = Transformer.from_crs(4326, source.crs, always_xy=True).transform(longitude, latitude)
            row, col = source.index(x, y)
            if row < 0 or col < 0 or row >= source.height or col >= source.width:
                raise HTTPException(422, "Coordinates outside analysis grid")
            value = source.read(1, window=rasterio.windows.Window(col, row, 1, 1))[0, 0]
            if value == source.nodata:
                return {"score": None, "meaning": "Masked or outside forest-like domain"}
        return {
            "score": float(value),
            "meaning": "uncalibrated annual forest-loss-reference score",
            "resolution_m": 30,
        }

    class FireQuery(BaseModel):
        bbox: list[float] = Field(min_length=4, max_length=4)
        days: int = Field(default=3, ge=1, le=10)

    @app.post("/api/fire-observations")
    def fire_observations(query: FireQuery):
        from shapely.geometry import box, mapping
        from ecosentinel.geometry import validate_geometry

        validate_geometry(mapping(box(*query.bbox)))
        return fetch_firms(query.bbox, query.days)

    app.state.queue = queue
    return app


app = create_app()
