"""Check PWA icon dimensions, font assets and the built client credential boundary."""

import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    public = ROOT / "frontend/public"
    manifest = json.loads((public / "manifest.webmanifest").read_text())
    assert manifest["display"] == "standalone"
    sizes = []
    for icon in manifest["icons"]:
        data = (public / icon["src"].lstrip("/")).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        width, height = struct.unpack(">II", data[16:24])
        assert icon["sizes"] == f"{width}x{height}"
        sizes.append(width)
    assert sorted(sizes) == [192, 512]
    assert len(list((public / "assets/fonts").glob("*.woff2"))) == 6
    assert len(list((public / "licenses").glob("*.txt"))) == 4
    dist = ROOT / "frontend/dist"
    files = [
        path
        for path in dist.rglob("*")
        if path.suffix in {".html", ".js", ".css", ".json", ".map"}
    ]
    assert files and (dist / "index.html").exists(), "Build the frontend first"
    fixture = json.loads((ROOT / ".local/pwa-identities.json").read_text())
    for path in files:
        content = path.read_bytes()
        for user in fixture["users"].values():
            assert user["bearer_token"].encode() not in content, (
                "Fixture credential found in client build"
            )
    print(
        json.dumps(
            {
                "standalone_manifest": True,
                "verified_icon_sizes": sizes,
                "self_hosted_fonts": 6,
                "font_license_files": 4,
                "built_client_contains_fixture_tokens": False,
                "checked_text_artifacts": len(files),
                "real_funds_moved": False,
            }
        )
    )


if __name__ == "__main__":
    main()
