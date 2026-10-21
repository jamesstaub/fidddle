"""Print the CHANGELOG section of one version (used for the text of a GitHub release).

  python tools/changelog_notes.py 0.2.0        # the section "## [0.2.0] - date"; falls back to "[Unreleased]"
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def section(text, version):
    for name in (re.escape(version), "Unreleased"):
        m = re.search(rf"^## \[{name}\][^\n]*\n(.*?)(?=^## \[|^\[[^\]]+\]: |\Z)", text, re.S | re.M)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return ""


if __name__ == "__main__":
    version = sys.argv[1] if len(sys.argv) > 1 else (ROOT / "VERSION").read_text().strip()
    notes = section((ROOT / "CHANGELOG.md").read_text(), version)
    if not notes:
        sys.exit(f"no CHANGELOG section for {version}")
    print(notes)
