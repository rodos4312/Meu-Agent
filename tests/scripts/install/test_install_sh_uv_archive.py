"""Exercise the real uv bootstrap with bundled bytes and HTTP failures."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import os
from pathlib import Path
import shlex
import subprocess
import tarfile
import threading

import pytest

pytestmark = pytest.mark.platforms("posix")
INSTALLER = Path(__file__).resolve().parents[3] / "scripts/install.sh"


def archive_bytes():
    output = io.BytesIO()
    body = b'#!/bin/sh\necho "uv fixture"\n'
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        entry = tarfile.TarInfo("uv-test/uv")
        entry.size = len(body)
        entry.mode = 0o755
        archive.addfile(entry, io.BytesIO(body))
    return output.getvalue()


def bootstrap(tmp_path, digest, url, archive=None):
    environment = {**os.environ, "HOME": str(tmp_path), "HERMES_HOME": str(tmp_path / "state"),
                   "HERMES_RUNTIME_DIR": str(tmp_path / "tools")}
    environment.pop("HERMES_UV_ARCHIVE", None)
    if archive is not None:
        environment["HERMES_UV_ARCHIVE"] = str(archive)
    q = shlex.quote
    script = f'''source {q(str(INSTALLER))} --manifest
uv_bootstrap_target() {{ echo linux-x64; }}
uv_bootstrap_pin() {{ UV_PIN_VERSION=fixture; UV_PIN_URL={q(url)}; UV_PIN_SHA256={q(digest)}; }}
ensure_uv
'''
    return subprocess.run(["bash", "-c", script], env=environment, text=True,
                          capture_output=True, timeout=30)


def test_bundled_archive_works_without_network(tmp_path):
    contents = archive_bytes()
    bundle = tmp_path / "bundled archive.tar.gz"
    bundle.write_bytes(contents)
    result = bootstrap(tmp_path, hashlib.sha256(contents).hexdigest(), "http://127.0.0.1:1/never", bundle)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "tools/uv-fixture-linux-x64/uv").is_file()
    assert "Using bundled uv" in result.stdout


def test_corrupt_bundle_is_rejected_before_execution(tmp_path):
    bundle = tmp_path / "bundle.tar.gz"
    bundle.write_bytes(archive_bytes())
    result = bootstrap(tmp_path, "0" * 64, "http://127.0.0.1:1/never", bundle)
    assert result.returncode != 0
    assert "digest mismatch" in result.stdout + result.stderr
    assert not (tmp_path / "tools/uv-fixture-linux-x64/uv").exists()


def test_missing_bundle_fails_without_network_fallback(tmp_path):
    result = bootstrap(tmp_path, "0" * 64, "http://127.0.0.1:1/never", tmp_path / "missing")
    assert result.returncode != 0
    assert "failed to stage bundled uv" in result.stdout + result.stderr


def test_download_recovers_after_http_503(tmp_path):
    contents = archive_bytes()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if len(requests) == 1:
                self.send_response(503)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(contents)))
            self.end_headers()
            self.wfile.write(contents)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        result = bootstrap(tmp_path, hashlib.sha256(contents).hexdigest(),
                           f"http://127.0.0.1:{server.server_port}/uv.tar.gz")
        assert result.returncode == 0, result.stdout + result.stderr
        assert len(requests) == 2
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
