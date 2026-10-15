"""Restore private model secrets and encrypt generated results on an ephemeral runner."""

import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tarfile


def restore(destination, expected_sha256):
    encoded = "".join(os.environ.get(f"MODEL_PART_{i}", "") for i in range(8))
    data = base64.b64decode(encoded, validate=True)
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("Private model bundle checksum mismatch")
    bundle = json.loads(gzip.decompress(data))
    expected = {"model.onnx", "config.json", "metrics.json", "onnx.json"}
    if bundle["format"] != "ecosentinel-build-assets-v1":
        raise ValueError("Unexpected model bundle format")
    entries = bundle["files"]
    if len(entries) != 4 or {entry["path"] for entry in entries} != expected:
        raise ValueError("Unexpected private model files")
    destination = Path(destination)
    destination.mkdir(mode=0o755, parents=True, exist_ok=False)
    for entry in entries:
        target = destination / entry["path"]
        target.write_bytes(base64.b64decode(entry["data"], validate=True))
        target.chmod(0o444)
    print("Verified private model bundle restored; no weights logged")


def seal(directory, destination):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = base64.b64decode(os.environ["OUTPUT_KEY"], validate=True)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        archive.add(directory, arcname="real-analysis")
    nonce = os.urandom(12)
    Path(destination).write_bytes(
        nonce + AESGCM(key).encrypt(nonce, buffer.getvalue(), b"ecosentinel-real-v1")
    )
    print("Generated results encrypted; model files are excluded")


if __name__ == "__main__":
    {"restore": restore, "seal": seal}[sys.argv[1]](*sys.argv[2:])
