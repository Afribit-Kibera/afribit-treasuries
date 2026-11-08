"""Export or check the frontend contract without starting the server."""

import argparse
import json
from pathlib import Path

from clans.api import create_app


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--live", action="store_true", help="Export the standalone production API"
    )
    parser.add_argument("--output", type=Path, default=Path("docs/openapi.json"))
    args = parser.parse_args()
    if args.live:
        from clans.live_app import create_app as create_live_app
        from clans.live_config import LiveSettings

        app = create_live_app(
            LiveSettings(
                environment="test",
                database_url="sqlite://",
                session_secret="docs-only-" * 8,
                public_origin="http://localhost:8410",
                rp_id="localhost",
            )
        )
        if args.output == Path("docs/openapi.json"):
            args.output = Path("docs/api/clans-live-openapi.json")
    else:
        app = create_app()
    try:
        content = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
        if args.check:
            if (
                not args.output.exists()
                or args.output.read_text(encoding="utf-8") != content
            ):
                print("OpenAPI contract differs; regenerate it before handoff.")
                return 1
            print("OpenAPI contract matches implementation.")
            return 0
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
        print(f"Exported OpenAPI contract to {args.output}")
        return 0
    finally:
        (app.state.security.engine if args.live else app.state.engine).dispose()


if __name__ == "__main__":
    raise SystemExit(main())
