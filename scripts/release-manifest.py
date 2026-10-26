"""Record the exact source and the already tested distribution files.

Usage: release-manifest.py <folder> <version> <target>
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

folder, version, target = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
manifest = folder / "release-manifest.json"
if manifest.exists():
    raise SystemExit("Release manifest already exists")
files = sorted([*folder.glob("*.zip"), *folder.glob("*.tar.gz")])
assert files, "no release archives found"
sha256 = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
record = {"sourceCommit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
          "version": version, "platform": target,
          "rustc": subprocess.check_output(["rustc", "--version"], text=True).strip(),
          "files": [{"name": p.name, "sha256": sha256(p), "size": p.stat().st_size} for p in files]}
manifest.write_text(json.dumps(record, indent=2) + "\n")
files.append(manifest)
(folder / "SHA256SUMS.txt").write_text("".join(f"{sha256(p)}  {p.name}\n" for p in files))
