"""Release inputs are deliberately listed; private working files cannot be swept in."""

import hashlib
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from release_archive import build_archive  # noqa: E402


@pytest.fixture
def source(tmp_path):
    files = {
        "backend/src/clans/safe.py": "# reviewed source",
        "frontend/public/theme.js": "// reviewed theme",
        "scripts/release-files.json": json.dumps(
            {"backend": ["backend/src/clans/safe.py"], "public": ["frontend/public/theme.js"]}
        ),
        "frontend/dist/theme.js": "// reviewed theme",
        "frontend/dist/index.html": "<!doctype html>",
        "frontend/dist/assets/index-12345678.js": "// generated bundle",
        "frontend/dist/.vite/manifest.json": json.dumps(
            {"index.html": {"file": "assets/index-12345678.js", "isEntry": True}}
        ),
    }
    for name, contents in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "backend", "scripts", "frontend/public"], check=True
    )
    return tmp_path


@pytest.mark.parametrize("backend,prefix", [(True, None), (False, ""), (True, "static")])
def test_backend_static_and_combined_manifests(source, backend, prefix):
    output = source / "release.tar.gz"
    manifest = build_archive(source, output, backend=backend, static_prefix=prefix)
    with tarfile.open(output) as archive:
        stored = json.load(archive.extractfile("release-manifest.json"))
        assert stored == manifest
        for name, expected in stored.items():
            assert hashlib.sha256(archive.extractfile(name).read()).hexdigest() == expected
        assert ("backend/src/clans/safe.py" in stored) == backend
        if prefix is not None:
            name = (prefix + "/" if prefix else "") + "theme.js"
            assert name in stored


def test_unexpected_static_file_blocks_archive(source):
    (source / "frontend/dist/private.json").write_text("synthetic secret", encoding="utf-8")
    with pytest.raises(ValueError, match="Unexpected or missing"):
        build_archive(source, source / "release.tar.gz", backend=False, static_prefix="")
    assert not (source / "release.tar.gz").exists()


def test_reviewed_about_entry_is_included_without_allowing_other_html(source):
    dist = source / "frontend/dist"
    manifest = dist / ".vite/manifest.json"
    entries = json.loads(manifest.read_text(encoding="utf-8"))
    entries["about/index.html"] = {"file": "assets/about-12345678.js", "isEntry": True}
    manifest.write_text(json.dumps(entries), encoding="utf-8")
    (dist / "about").mkdir()
    (dist / "about/index.html").write_text("<!doctype html>", encoding="utf-8")
    (dist / "assets/about-12345678.js").write_text("// reviewed entry", encoding="utf-8")
    result = build_archive(source, source / "about.tar.gz", backend=False, static_prefix="")
    assert "about/index.html" in result
    (dist / "private.html").write_text("unlisted", encoding="utf-8")
    with pytest.raises(ValueError, match="Unexpected or missing"):
        build_archive(source, source / "refuse.tar.gz", backend=False, static_prefix="")


def test_modified_public_copy_is_not_released(source):
    (source / "frontend/dist/theme.js").write_text("unexpected copy", encoding="utf-8")
    with pytest.raises(ValueError, match="differs"):
        build_archive(source, source / "release.tar.gz", backend=False, static_prefix="")


def test_tracked_source_hardlink_is_rejected(source):
    path = source / "backend/src/clans/safe.py"
    os.link(path, source / "same-file")
    with pytest.raises(ValueError, match="regular file"):
        build_archive(source, source / "release.tar.gz")


@pytest.mark.skipif(os.name != "posix", reason="Linux release link boundary")
def test_tracked_source_symlink_is_rejected(source):
    path = source / "backend/src/clans/safe.py"
    path.unlink()
    path.symlink_to(source / "frontend/public/theme.js")
    with pytest.raises(ValueError, match="links"):
        build_archive(source, source / "release.tar.gz")


def test_every_backend_source_file_is_in_the_release():
    """A module, migration or service missing from the list would break the deployed app."""
    root = Path(__file__).resolve().parents[2]
    listed = set(
        json.loads((root / "scripts/release-files.json").read_text(encoding="utf-8"))["backend"]
    )
    try:
        tracked = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "backend/src",
                "backend/migrations",
                "backend/tests",
                "ops",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("Needs a Git checkout")
    if not tracked:
        pytest.skip("Needs a Git checkout")
    missing = sorted(name for name in tracked if name not in listed)
    assert missing == [], "Add these to scripts/release-files.json: " + ", ".join(missing)
