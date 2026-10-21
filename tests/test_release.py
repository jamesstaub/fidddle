import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import changelog_notes  # noqa: E402
import set_version  # noqa: E402


def test_version_is_semver_and_consistent():
    a, b = set_version.versions()
    assert set_version.SEMVER.match(a)
    assert a == b                                            # VERSION and package-info.json agree
    import fidddle
    assert fidddle.__version__ == a


def test_changelog_has_notes_for_the_next_release():
    notes = changelog_notes.section((ROOT / "CHANGELOG.md").read_text(), (ROOT / "VERSION").read_text().strip())
    assert notes                                             # either the version's own section or [Unreleased]


def test_set_version_moves_unreleased_notes(tmp_path, monkeypatch):
    (tmp_path / "package" / "fidddle").mkdir(parents=True)
    (tmp_path / "VERSION").write_text("0.1.0\n")
    (tmp_path / "package" / "fidddle" / "package-info.json").write_text(json.dumps({"version": "0.1.0"}))
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n\n### Added\n- thing\n\n[Unreleased]: https://github.com/x/y/commits/main\n")
    monkeypatch.setattr(set_version, "ROOT", tmp_path)
    set_version.set_version("0.2.0")
    text = (tmp_path / "CHANGELOG.md").read_text()
    assert "## [0.2.0] - " in text and "[0.2.0]: " in text
    assert changelog_notes.section(text, "0.2.0").startswith("### Added")
    assert (tmp_path / "VERSION").read_text().strip() == "0.2.0"
    assert json.loads((tmp_path / "package" / "fidddle" / "package-info.json").read_text())["version"] == "0.2.0"


def test_semver_check_rejects_other_formats():
    assert not set_version.SEMVER.match("1.2")
    assert not set_version.SEMVER.match("v1.2.3")
    assert set_version.SEMVER.match("1.2.3-rc.1")


def test_cli_reports_the_version():
    out = subprocess.run([sys.executable, "-m", "fidddle", "--version"], cwd=ROOT, capture_output=True, text=True)
    assert out.stdout.strip() == "fidddle " + (ROOT / "VERSION").read_text().strip()
