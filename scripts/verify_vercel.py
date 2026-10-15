"""Verify published scientific artifacts against the packaged local checksums."""

import hashlib
import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from ecosentinel.common import ROOT, read_json, utcnow, write_json

origin = sys.argv[1].rstrip("/")
package = ROOT / "apps/web/public/evidence"


def fetch(path):
    with urllib.request.urlopen(origin + path, timeout=60) as response:
        return response.read()


health = json.loads(fetch("/health"))
assert health["mode"] == "evidence" and health["analysis_available"] is False
catalog = read_json(package / "catalog.json")
assert json.loads(fetch("/evidence/catalog.json")) == catalog
for job in catalog["jobs"]:
    assert json.loads(fetch(f"/api/jobs/{job['id']}"))["report"] == job["report"]


def verify_asset(item):
    path, digest = item
    actual = hashlib.sha256(fetch("/evidence/" + path)).hexdigest()
    if actual != digest:
        raise ValueError(f"Published artifact checksum mismatch: {path}")
    return path


manifest = read_json(package / "checksums.json")
with ThreadPoolExecutor(max_workers=4) as executor:
    verified = list(executor.map(verify_asset, manifest.items()))
try:
    request = urllib.request.Request(
        origin + "/api/jobs",
        data=json.dumps(catalog["jobs"][0]["request"]).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(request, timeout=60)
    raise AssertionError("Viewer accepted new inference")
except urllib.error.HTTPError as error:
    assert error.code == 503
write_json(
    ROOT / "docs/vercel-verification.json",
    {
        "verified_at": utcnow(),
        "url": origin,
        "mode": "evidence",
        "analysis_available": False,
        "completed_jobs": len(catalog["jobs"]),
        "assets_verified_sha256": verified,
        "new_inference_status": 503,
        "deployment_id": sys.argv[2] if len(sys.argv) > 2 else None,
        "commit": None,
    },
)
print(f"Verified {len(verified)} public artifacts and {len(catalog['jobs'])} real analyses")
