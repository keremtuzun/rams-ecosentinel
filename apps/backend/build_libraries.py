"""Build the missing GDAL dependency from a checksum-verified upstream release."""

import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

URL = "https://github.com/libexpat/libexpat/releases/download/R_2_9_0/expat-2.9.0.tar.xz"
DIGEST = "1e6371862cc31999b368c3b89b49994f0677e1bab5f1b2b85ae3741f5d803051"
destination = Path(__file__).parent / "native_libraries"
destination.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix="expat-build-") as temp:
    archive = Path(temp) / "expat.tar.xz"
    with urllib.request.urlopen(URL, timeout=60) as response:
        data = response.read(10_000_000)
    if hashlib.sha256(data).hexdigest() != DIGEST:
        raise ValueError("Upstream runtime dependency checksum mismatch")
    archive.write_bytes(data)
    with tarfile.open(archive) as package:
        package.extractall(temp, filter="data")
    source = Path(temp) / "expat-2.9.0"
    subprocess.run(
        ["./configure", "--disable-static", "--without-xmlwf", "--without-docbook"], cwd=source, check=True
    )
    subprocess.run(["make", "-j2"], cwd=source, check=True)
    shutil.copyfile((source / "lib/.libs/libexpat.so.1").resolve(), destination / "libexpat.so.1")
    shutil.copyfile(source / "COPYING", destination / "EXPAT-LICENSE")
    (destination / "manifest.json").write_text(
        json.dumps(
            {
                "source": URL,
                "source_sha256": DIGEST,
                "library_sha256": hashlib.sha256((destination / "libexpat.so.1").read_bytes()).hexdigest(),
            }
        )
    )
print("Built checksum-verified Expat 2.9.0 for the Python geospatial runtime")
