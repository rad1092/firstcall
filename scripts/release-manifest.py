"""Record the exact source and the already tested macOS distribution files."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

folder = Path(sys.argv[1])
manifest = folder / "release-manifest.json"
if manifest.exists():
    raise SystemExit("Release manifest already exists")
files = sorted([*folder.glob("*.zip"), *folder.glob("*.tar.gz")])
assert len(files) == 2
sha256 = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
record = {"sourceCommit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
          "version": "0.3.1", "platform": "aarch64-apple-darwin",
          "rustc": subprocess.check_output(["rustc", "--version"], text=True).strip(),
          "signing": "ad-hoc integrity only; not notarized",
          "files": [{"name": p.name, "sha256": sha256(p), "size": p.stat().st_size} for p in files]}
manifest.write_text(json.dumps(record, indent=2) + "\n")
files.append(manifest)
(folder / "SHA256SUMS.txt").write_text("".join(f"{sha256(p)}  {p.name}\n" for p in files))
