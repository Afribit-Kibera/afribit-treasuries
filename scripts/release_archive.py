"""Build releases from reviewed tracked files, never recursive working directories.

The checked-in manifest is a positive list. Static outputs must be declared by
Vite or match an explicitly listed public asset byte-for-byte. Symlinks, hard
links, secret paths and unexpected build outputs fail closed.
"""

import hashlib
import io
import json
import re
import subprocess
import tarfile
from pathlib import Path, PurePosixPath


def safe_name(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError("Invalid release path")
    if any(
        part.lower() in {"secrets", ".git", ".local", "node_modules", "__pycache__"}
        or part.lower().startswith(".env")
        for part in path.parts
    ):
        raise ValueError("Secret or private directory in release")
    if path.suffix.lower() in {
        ".key",
        ".pem",
        ".macaroon",
        ".db",
        ".dump",
        ".backup",
        ".pyc",
    }:
        raise ValueError("Private file type in release")
    return path


def checked_file(root, name):
    safe_name(name)
    path = root / name
    if any(p.is_symlink() for p in [path, *path.parents] if p != root.parent):
        raise ValueError("Release paths must not be links")
    if (
        not path.is_file()
        or not path.resolve().is_relative_to(root.resolve())
        or path.stat().st_nlink != 1
    ):
        raise ValueError("Release input must be a regular file inside the source root")
    return path


def source_files(root):
    manifest = json.loads(
        (root / "scripts/release-files.json").read_text(encoding="utf-8")
    )
    tracked = set(
        subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached"],
            check=True,
            capture_output=True,
        )
        .stdout.decode()
        .split("\0")
    )
    names = manifest["backend"] + manifest["public"]
    if (
        "scripts/release-files.json" not in tracked
        or len(set(names)) != len(names)
        or not set(names) <= tracked
    ):
        raise ValueError("Every release input must be explicitly listed and tracked")
    for name in names:
        checked_file(root, name)
    return manifest


def static_files(root, manifest):
    dist = root / "frontend/dist"
    vite = json.loads(
        checked_file(dist, ".vite/manifest.json").read_text(encoding="utf-8")
    )
    names = {"index.html", ".vite/manifest.json"}
    for source, entry in vite.items():
        if source == "about/index.html" and entry.get("isEntry"):
            names.add(source)
        outputs = [entry["file"], *entry.get("css", []), *entry.get("assets", [])]
        for name in outputs:
            if not re.fullmatch(
                r"assets/[A-Za-z0-9_.-]+-[A-Za-z0-9_-]{8,}\.(js|css|woff2|webp|png|svg)",
                name,
            ):
                raise ValueError("Unexpected generated asset name")
            names.add(name)
    for source in manifest["public"]:
        name = str(PurePosixPath(source).relative_to("frontend/public"))
        if (
            checked_file(dist, name).read_bytes()
            != checked_file(root, source).read_bytes()
        ):
            raise ValueError("Public asset differs from reviewed input")
        names.add(name)
    outputs = list(dist.rglob("*"))
    if any(p.is_symlink() for p in outputs):
        raise ValueError("Static outputs must not contain links")
    actual = {p.relative_to(dist).as_posix() for p in outputs if not p.is_dir()}
    if actual != names:
        raise ValueError(
            "Unexpected or missing static output: " + str(sorted(actual ^ names))
        )
    return [(checked_file(dist, name), name) for name in sorted(names)]


def build_archive(root, target, *, backend=True, static_prefix=None):
    root, target = Path(root), Path(target)
    manifest = source_files(root)
    files = [(checked_file(root, n), n) for n in manifest["backend"]] if backend else []
    if static_prefix is not None:
        files += [
            (p, str(PurePosixPath(static_prefix) / n))
            for p, n in static_files(root, manifest)
        ]
    target.parent.mkdir(parents=True, exist_ok=True)
    # Validate everything before opening the output archive or attempting upload.
    contents = [(name, path.read_bytes()) for path, name in files]
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in contents}
    contents.append(
        (
            "release-manifest.json",
            (json.dumps(hashes, sort_keys=True, indent=2) + "\n").encode(),
        )
    )
    with tarfile.open(target, "w:gz") as package:
        for name, data in contents:
            safe_name(name)
            entry = tarfile.TarInfo(name)
            entry.mode, entry.size, entry.mtime = 0o644, len(data), 0
            package.addfile(entry, io.BytesIO(data))
    return hashes
