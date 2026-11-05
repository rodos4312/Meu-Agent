"""CI-only controller: the receipt token belongs to this live job, not the rebooted job."""
import base64
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import urlencode

REPO = "rodos4312/Meu-Agent"


class TransientGitHubError(RuntimeError):
    pass


def gh(*args):
    try:
        result = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=45, check=False)
    except subprocess.TimeoutExpired as exc:
        raise TransientGitHubError("GitHub request timed out") from exc
    if result.returncode:
        if re.search(r"HTTP (?:429|5\d\d)\b|connection reset|TLS handshake timeout", result.stderr, re.IGNORECASE):
            raise TransientGitHubError("GitHub temporarily refused the request")
        raise RuntimeError(f"GitHub command failed: {result.stderr.strip()}")
    return result.stdout


def wait_for(read, description):
    deadline = time.monotonic() + 480
    while time.monotonic() < deadline:
        try:
            if result := read():
                return result
        except TransientGitHubError as exc:
            print(f"{exc}; retrying within the receipt deadline", flush=True)
        time.sleep(5)
    raise TimeoutError(description)


def handoff(directory, run, attempt):
    name = f"meu-reboot-public-{attempt}"

    def published():
        inventory = json.loads(gh("api", f"repos/{REPO}/actions/runs/{run}/artifacts?per_page=100"))
        return any(row["name"] == name for row in inventory["artifacts"])

    wait_for(published, "Windows public-key artifact did not arrive")
    gh("run", "download", run, "--repo", REPO, "--name", name, "--dir", str(directory))
    baseline = json.loads((directory / "baseline.json").read_text(encoding="utf-8-sig"))
    assert baseline["run"] == run and baseline["attempt"] == attempt
    token = os.environ["GH_TOKEN"].encode()
    # Installation tokens can exceed OAEP's single-message limit. A protected
    # header authenticates the length/hash of the ordered encrypted chunks.
    header = json.dumps({"length": len(token), "sha256": hashlib.sha256(token).hexdigest()}).encode()
    chunks = [header, *(token[i:i + 200] for i in range(0, len(token), 200))]
    if len(chunks) > 16:
        raise ValueError("Receipt token exceeds the bounded encrypted envelope")
    encrypted = []
    for chunk in chunks:
        result = subprocess.run([
            "openssl", "pkeyutl", "-encrypt", "-pubin", "-inkey", str(directory / "public.pem"),
            "-pkeyopt", "rsa_padding_mode:oaep", "-pkeyopt", "rsa_oaep_md:sha256",
        ], input=chunk, capture_output=True, check=True, timeout=30)
        encrypted.append(base64.b64encode(result.stdout).decode())
    (directory / "envelope.bin").write_text(json.dumps(encrypted), encoding="utf-8")
    print("Encrypted the controller job's repository-scoped receipt token for the disposable Windows VM.")


def receipt(directory, run, attempt):
    baseline = json.loads((directory / "baseline.json").read_text(encoding="utf-8-sig"))
    query = urlencode({"check_name": "Meu reboot receipt", "per_page": 30, "filter": "all"})

    def received():
        checks = json.loads(gh("api", f"repos/{REPO}/commits/{os.environ['GITHUB_SHA']}/check-runs?{query}"))
        return next((row for row in checks["check_runs"]
                     if row["name"] == "Meu reboot receipt" and row["external_id"] == f"{run}-{attempt}"), None)

    check = wait_for(received, "No authenticated post-boot receipt arrived")
    proof = json.loads(check["output"]["summary"])
    assert check["conclusion"] == "success", proof
    assert proof["nonce"] == baseline["nonce"]
    assert proof["before_boot_utc"] == baseline["before_boot_utc"]
    assert datetime.fromisoformat(proof["after_boot_utc"]) > datetime.fromisoformat(baseline["before_boot_utc"])
    assert proof["run"] == run and proof["attempt"] == attempt
    (directory / "receipt.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
    print("Verified an authenticated receipt from a genuinely later Windows boot.")


def main():
    if (os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_REPOSITORY") != REPO
            or os.environ.get("GITHUB_REF") != "refs/heads/dev/meu-foundation"):
        raise RuntimeError("This probe is restricted to the Meu development workflow")
    mode, folder = sys.argv[1:]
    directory = Path(folder)
    directory.mkdir(parents=True, exist_ok=True)
    {"handoff": handoff, "wait": receipt}[mode](directory, os.environ["GITHUB_RUN_ID"], os.environ["GITHUB_RUN_ATTEMPT"])


if __name__ == "__main__":
    main()
