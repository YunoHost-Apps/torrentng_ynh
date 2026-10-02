#!/usr/bin/env python3
"""Mirror the upstream YunoHost package and pin its newest published bundles."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = "snapetech/TorrentNG"
API = f"https://api.github.com/repos/{REPO}/releases/latest"


def fetch(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "torrentng-yunohost-sync",
            **({"Authorization": f"Bearer {os.environ['GH_TOKEN']}"} if os.getenv("GH_TOKEN") else {}),
        },
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read()


def main() -> None:
    release = json.loads(fetch(API))
    tag = release.get("tag_name", "")
    if not tag.startswith("main-"):
        raise SystemExit(f"Latest upstream release is not a main release: {tag!r}")
    assets = {asset["name"]: asset["browser_download_url"] for asset in release["assets"]}
    checksums_name = f"SHA256SUMS-{tag}.txt"
    checksums_url = assets.get(checksums_name)
    if not checksums_url:
        raise SystemExit(f"Release {tag} has no {checksums_name}")
    checksums = fetch(checksums_url).decode("ascii")

    version = tag.removeprefix("main-")
    bundle_data: dict[str, tuple[str, str]] = {}
    for arch, suffix in (("amd64", "linux-amd64"), ("arm64", "linux-arm64")):
        name = f"torrentng-yunohost-{tag}-{suffix}.tar.gz"
        url = assets.get(name)
        if not url:
            raise SystemExit(f"Release {tag} is missing required bundle {name}")
        match = re.search(rf"^([0-9a-f]{{64}})  {re.escape(name)}$", checksums, re.MULTILINE)
        if not match:
            raise SystemExit(f"{checksums_name} has no valid SHA256 for {name}")
        bundle_data[arch] = (url, match.group(1))

    with tempfile.TemporaryDirectory(prefix="torrentng-ynh-sync-") as temp:
        upstream = Path(temp) / "upstream"
        subprocess.run(
            ["git", "clone", "--quiet", "--depth", "1", f"https://github.com/{REPO}.git", str(upstream)],
            check=True,
        )
        source = upstream / "packaging/yunohost"
        if not source.is_dir():
            raise SystemExit("Upstream packaging/yunohost directory is missing")
        for child in ROOT.iterdir():
            if child.name in {".git", ".github", "LICENSE"}:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        for child in source.iterdir():
            target = ROOT / child.name
            if child.is_dir():
                shutil.copytree(child, target)
            else:
                shutil.copy2(child, target)

    manifest = ROOT / "manifest.toml"
    text = manifest.read_text()
    for arch in ("amd64", "arm64"):
        url, sha256 = bundle_data[arch]
        text, urls = re.subn(
            rf"(?m)^(\s*{arch}\.url\s*=\s*)\"[^\"]*\"$",
            lambda match: f'{match.group(1)}"{url}"',
            text,
            count=1,
        )
        text, hashes = re.subn(
            rf"(?m)^(\s*{arch}\.sha256\s*=\s*)\"[^\"]*\"$",
            lambda match: f'{match.group(1)}"{sha256}"',
            text,
            count=1,
        )
        if urls != 1 or hashes != 1:
            raise SystemExit(f"Could not update {arch} bundle URL and checksum in manifest.toml")
    manifest.write_text(text)
    print(f"Synchronized upstream package files and {tag} bundles ({version}).")


if __name__ == "__main__":
    main()
