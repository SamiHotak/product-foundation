"""Write the OpenAPI schema as JSON. The frontend generates its typed API client from it.

Run: python -m app.scripts.export_openapi --out ../frontend/lib/api/openapi.json
     (or simply: make api-client)
Without --out the schema is printed to stdout.
"""

import argparse
import json
import sys
from pathlib import Path

from app.core.config import Environment, Settings
from app.main import create_app


def build_schema() -> str:
    """The schema as stable, pretty JSON (same output every time for the same code)."""
    settings = Settings(
        _env_file=None,
        environment=Environment.DEVELOPMENT,
        jobs_api_enabled=True,
        log_level="WARNING",
    )
    schema = create_app(settings).openapi()
    return json.dumps(schema, indent=2, ensure_ascii=True) + "\n"


def main(argv: list[str] | None = None) -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="file to write (default: stdout)")
    args = parser.parse_args(argv)
    schema = build_schema()
    if args.out is None:
        sys.stdout.write(schema)
        return
    # newline="\n": same bytes on Windows and Linux, so CI's diff stays clean.
    args.out.write_text(schema, encoding="utf-8", newline="\n")
    print(f"Wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
