import asyncio
import hmac
import json
import os
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

os.environ["ECOSENTINEL_INFERENCE_ENGINE"] = "onnx"
os.environ["ECOSENTINEL_ARTIFACTS"] = str(Path(__file__).parent / "runtime")
app = FastAPI(title="EcoSentinel compute", docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def authenticate(request: Request, call_next):
    expected = os.environ.get("ECOSENTINEL_BACKEND_TOKEN", "")
    presented = request.headers.get("authorization", "")
    if not expected or not hmac.compare_digest(presented, "Bearer " + expected):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    if request.method == "POST":
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 16384:
                return JSONResponse({"detail": "Request exceeds 16 KB"}, status_code=413)
        request._body = bytes(body)
    return await call_next(request)


@app.get("/health")
def health():
    from ecosentinel.common import ARTIFACTS
    from ecosentinel.onnx_runtime import load_onnx

    _, _, metrics = load_onnx(ARTIFACTS / "models/habitat-7729")
    return {
        "status": "ok",
        "engine": "onnx",
        "checkpoint_sha256": metrics["checkpoint_sha256"],
        "storage_configured": bool(os.environ.get("BLOB_READ_WRITE_TOKEN")),
    }


def compute(payload):
    try:
        action = payload.get("action")
        timeout = 235 if action in ["before", "after", "infer"] else 45
        completed = subprocess.run(
            [sys.executable, "-m", "ecosentinel.cloud_rpc"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            cwd=Path(__file__).parent,
            env={
                **os.environ,
                "PYTHONPATH": os.pathsep.join(sys.path),
                "LD_LIBRARY_PATH": str(Path(__file__).parent / "native_libraries")
                + os.pathsep
                + os.environ.get("LD_LIBRARY_PATH", ""),
            },
        )
        if completed.returncode or not completed.stdout.strip():
            import re

            names = re.findall(r"(?:^|\n)([A-Za-z]+(?:Error|Exception)):", completed.stderr)
            diagnostic = completed.stderr[-1600:]
            for key in ["ECOSENTINEL_BACKEND_TOKEN", "BLOB_READ_WRITE_TOKEN", "VERCEL_OIDC_TOKEN"]:
                secret = os.environ.get(key)
                if secret:
                    diagnostic = diagnostic.replace(secret, "[redacted]")
            print(
                json.dumps(
                    {
                        "event": "compute_child_failed",
                        "exit_code": completed.returncode,
                        "exception_types": names,
                        "diagnostic": diagnostic,
                    }
                )
            )
            return {"ok": False, "detail": "Cloud processing failed"}
        result = json.loads(completed.stdout)
        if not result.get("ok"):
            print(
                json.dumps(
                    {
                        "event": "compute_stage_failed",
                        "stage": action,
                        "type": result.get("type", "data_unavailable"),
                    }
                )
            )
        return result
    except subprocess.TimeoutExpired:
        return {"ok": False, "detail": "Analysis stage exceeded the server time limit"}
    except Exception as exc:
        print(json.dumps({"event": "compute_rpc_failed", "type": type(exc).__name__}))
        return {"ok": False, "detail": "Cloud processing failed"}


@app.post("/rpc")
async def rpc(request: Request):
    result = await asyncio.to_thread(compute, await request.json())
    return JSONResponse(result, status_code=200 if result.get("ok") else 422)
