"""Stage a self-contained, bounded Git history for the small Meu installer.

The original commits survive unchanged. A real shallow boundary excludes old
upstream history, not runtime files. No installed profile, venv, cache, credentials
or Git config is copied. The recipient clones/fetches this ordinary local remote.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile

BRANCH = "dev/meu-foundation"
REPOSITORY = "https://github.com/rodos4312/Meu-Agent-RC-private.git"


def git(root: Path, *args: str, data: str | None = None) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], input=data, text=True, encoding="utf-8",
        errors="strict", timeout=600,
    ).strip()


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stage(source: Path, output: Path, base: str, products: Path | None = None) -> dict:
    source = source.resolve()
    head = git(source, "rev-parse", "HEAD")
    git(source, "merge-base", "--is-ancestor", base, head)
    if git(source, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("Source seed requires a clean committed checkout")
    # Boundary commits have their entire trees included too. Their excluded
    # parents are represented by Git's normal shallow file, never forged commits.
    walk = git(source, "rev-list", "--boundary", head, "^" + base).splitlines()
    commits = sorted({base, *(line.lstrip("-") for line in walk)})
    parents = git(source, "rev-list", "--parents", "--no-walk", "--stdin",
                  data="\n".join(commits) + "\n").splitlines()
    selected = set(commits)
    shallow = [parts[0] for line in parents if (parts := line.split())
               and any(parent not in selected for parent in parts[1:])]
    objects = git(source, "rev-list", "--objects", "--no-walk", "--stdin",
                  data="\n".join(commits) + "\n")
    ids = sorted({line.split()[0] for line in objects.splitlines()})
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="meu-source-seed-") as temporary:
        bare = Path(temporary) / "source.git"
        git(source, "init", "--bare", "--template=", str(bare))
        git(source, "pack-objects", "--delta-base-offset", "--compression=6",
            str(bare / "objects" / "pack" / "pack"), data="\n".join(ids) + "\n")
        if shallow:
            (bare / "shallow").write_text("\n".join(sorted(shallow)) + "\n", encoding="ascii")
        git(bare, "update-ref", "refs/heads/" + BRANCH, head)
        git(bare, "symbolic-ref", "HEAD", "refs/heads/" + BRANCH)
        git(bare, "fsck", "--full", "--strict")
        archive = output / "meu-source-seed.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as bundle:
            # Git packs are already compressed. Exclude generated sample hooks.
            for item in sorted(bare.rglob("*")):
                relative = item.relative_to(bare)
                if item.is_file() and relative.parts[0] in {"objects", "refs", "HEAD", "config", "shallow"}:
                    bundle.write(item, "source.git/" + relative.as_posix())
    if products is not None:
        required = {"web": ("index.html", "hermes_cli/web_dist"),
                    "tui/dist": ("entry.js", "ui-tui/dist")}
        with zipfile.ZipFile(archive, "a", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
            for name, (entry, destination) in required.items():
                product = products / name
                if not (product / entry).is_file():
                    raise ValueError(f"Missing compiled source product: {name}/{entry}")
                for item in sorted(product.rglob("*")):
                    if item.is_file():
                        if item.is_symlink():
                            raise ValueError("Compiled products must not contain symlinks")
                        bundle.write(item, "products/" + destination + "/" + item.relative_to(product).as_posix())
    manifest = {"schema": 1, "file": archive.name, "commit": head,
                "base": base, "branch": BRANCH, "repository": REPOSITORY,
                "sha256": _digest(archive),
                "size": archive.stat().st_size}
    (output / "meu-source-seed.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--products", type=Path)
    args = parser.parse_args()
    print(json.dumps(stage(args.source, args.out, args.base, args.products)))


if __name__ == "__main__":
    main()
