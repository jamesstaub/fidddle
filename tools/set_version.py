"""Set the release version (semantic versioning) in every place that carries it, and close the CHANGELOG section.

  python tools/set_version.py 0.2.0          # VERSION, package-info.json, CHANGELOG ([Unreleased] becomes [0.2.0])
  python tools/set_version.py 0.2.0 --check  # only check that everything agrees

Then: commit, tag with "git tag v0.2.0", and push the tag. The release workflow does the rest (README, "Releases").
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$")
REPO = "https://github.com/jamesstaub/fidddle"


def versions():
    info = json.loads((ROOT / "package" / "fidddle" / "package-info.json").read_text())
    return (ROOT / "VERSION").read_text().strip(), info["version"]


def set_version(v):
    (ROOT / "VERSION").write_text(v + "\n")
    p = ROOT / "package" / "fidddle" / "package-info.json"
    info = json.loads(p.read_text())
    info["version"] = v
    p.write_text(json.dumps(info, indent="\t") + "\n")
    c = ROOT / "CHANGELOG.md"
    t = c.read_text()
    if f"## [{v}]" in t:
        sys.exit(f"CHANGELOG already has a section for {v}")
    prev = re.findall(r"^## \[(\d[^\]]*)\]", t, re.M)
    t = t.replace("## [Unreleased]\n", f"## [Unreleased]\n\n## [{v}] - {date.today().isoformat()}\n", 1)
    link_prev = f"{REPO}/compare/v{prev[0]}...v{v}" if prev else f"{REPO}/releases/tag/v{v}"
    t = re.sub(r"^\[Unreleased\]: .*$", f"[Unreleased]: {REPO}/compare/v{v}...HEAD\n[{v}]: {link_prev}", t, flags=re.M)
    c.write_text(t)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    v = sys.argv[1].lstrip("v")
    if not SEMVER.match(v):
        sys.exit(f"{v!r} is not a semantic version (MAJOR.MINOR.PATCH, optional -prerelease)")
    if "--check" in sys.argv:
        a, b = versions()
        sys.exit(0 if a == b == v else f"VERSION {a}, package-info.json {b}, expected {v}")
    set_version(v)
    print(f"version set to {v}. Next: review CHANGELOG.md, commit, git tag v{v}, git push origin main v{v}")
