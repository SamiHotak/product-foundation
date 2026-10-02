#!/usr/bin/env python3
"""Turn a fresh copy of this template into your own product (name, tagline, color, image path).

    python scripts/new_product.py --name AskDocs --tagline "Ask questions about your documents." \
        --accent "#0F766E" --accent-dark "#5EEAD4" --github-user my-user --repo askdocs --dry-run

Run it ONCE, on a fresh copy, from the repository root. Without --dry-run it changes the files.
It only changes the few places that hold the product identity (listed in docs/NEW_PRODUCT.md).
It stops and changes nothing if one of them no longer looks as expected (for example because
you already changed it by hand). No packages needed: plain Python 3.
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,38}$")
USER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
OLD_NAME = "Foundation"


class ChangeError(Exception):
    """A file does not look like the template any more."""


@dataclass
class Edit:
    path: str
    pattern: str
    replacement: str
    count: int = 1


def apply_edits(root: Path, edits: list[Edit], *, write: bool) -> list[str]:
    """Check every edit first; write only if all of them match. Returns the changed files."""
    results: dict[Path, str] = {}
    for edit in edits:
        file = root / edit.path
        if not file.is_file():
            raise ChangeError(f"{edit.path} is missing. Is this the repository root?")
        text = results.get(file, file.read_text(encoding="utf-8"))
        new, found = re.subn(edit.pattern, edit.replacement, text, flags=re.MULTILINE)
        if found != edit.count:
            raise ChangeError(
                f"{edit.path}: expected {edit.count} place(s) for `{edit.pattern}`, found {found}. "
                "Use this script only once, on a fresh copy of the template."
            )
        results[file] = new
    if write:
        for file, text in results.items():
            file.write_text(text, encoding="utf-8", newline="")
    return sorted(str(f.relative_to(root)) for f in results)


def literal(value: str) -> str:
    """A value that is inserted as it is (backslashes etc. must not act as regex groups)."""
    return value.replace("\\", "\\\\")


def build_edits(args: argparse.Namespace) -> list[Edit]:
    name = literal(args.name)
    json_name = literal(json.dumps(args.name)[1:-1])  # inside a TypeScript/JSON string
    tagline = literal(json.dumps(args.tagline)[1:-1])
    monogram = literal(json.dumps(args.monogram or args.name[0].upper())[1:-1])
    edits = [
        Edit("frontend/config/product.ts", r'^(  name: )"Foundation",', rf'\g<1>"{json_name}",'),
        Edit(
            "frontend/config/product.ts",
            r'^(  tagline: )".*",',
            rf'\g<1>"{tagline}",',
        ),
        Edit("frontend/config/product.ts", r'^(  monogram: )"[^"]*",', rf'\g<1>"{monogram}",'),
        Edit(
            "frontend/config/product.ts",
            r'accent: \{ light: "#[0-9A-Fa-f]{6}", dark: "#[0-9A-Fa-f]{6}" \}',
            f'accent: {{ light: "{args.accent}", dark: "{args.accent_dark}" }}',
        ),
        Edit("deploy/docker-compose.dev.yml", r"^(  APP_NAME: )Foundation ", rf"\g<1>{name} "),
        Edit("deploy/.env.example", r"^APP_NAME=Foundation$", f"APP_NAME={name}"),
        Edit(
            "deploy/.env.example",
            r"^IMAGE_PREFIX=ghcr\.io/\S+$",
            f"IMAGE_PREFIX=ghcr.io/{args.github_user.lower()}/{args.repo.lower()}",
        ),
        Edit(
            "backend/app/core/config.py",
            r'app_name: str = "Product Foundation"',
            f'app_name: str = "{json_name}"',
        ),
        Edit(
            "backend/app/core/config.py",
            r'email_from: str = "Foundation <no-reply@localhost>"',
            f'email_from: str = "{json_name} <no-reply@localhost>"',
        ),
        Edit("frontend/package.json", r'^(  "name": )"[^"]+"', rf'\g<1>"{args.slug}-frontend"'),
        Edit(
            "frontend/package-lock.json",
            r'^(\s*"name": )"product-foundation-frontend"',
            rf'\g<1>"{args.slug}-frontend"',
            2,
        ),
        Edit(
            "frontend/tests/e2e/design-system.spec.ts",
            r"Dashboard · Foundation/",
            rf"Dashboard · {name}/",
        ),
        Edit(
            "frontend/tests/e2e/design-system.spec.ts",
            r'name: "Foundation home"',
            f'name: "{json_name} home"',
        ),
        Edit(
            "deploy/server-setup.md",
            r"ghcr\.io/samihotak/product-foundation",
            f"ghcr.io/{args.github_user.lower()}/{args.repo.lower()}",
        ),
    ]
    return edits


def validate(args: argparse.Namespace) -> str | None:
    if not 1 <= len(args.name) <= 40 or "\n" in args.name:
        return "--name must be 1 to 40 characters on one line."
    if not args.tagline.strip() or len(args.tagline) > 120:
        return "--tagline must be 1 to 120 characters."
    for flag, value in (("--accent", args.accent), ("--accent-dark", args.accent_dark)):
        if not HEX.match(value):
            return f"{flag} must look like #0F766E (a # and 6 letters/digits)."
    if not SLUG.match(args.slug):
        return "--slug: only small letters, digits and -, up to 39 characters."
    if not USER.match(args.github_user) or not SLUG.match(args.repo.lower()):
        return "--github-user / --repo: only letters, digits and - (GitHub rules)."
    if args.monogram is not None and not 1 <= len(args.monogram) <= 2:
        return "--monogram must be 1 or 2 characters."
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--name", required=True, help='product name, e.g. "AskDocs"')
    parser.add_argument("--tagline", required=True, help="one sentence: what it does for the user")
    parser.add_argument("--accent", required=True, help="brand color for light mode, e.g. #0F766E")
    parser.add_argument("--accent-dark", required=True, help="brand color for dark mode")
    parser.add_argument("--github-user", required=True, help="your GitHub user or organisation")
    parser.add_argument("--repo", required=True, help="the name of the new GitHub repository")
    parser.add_argument("--slug", help="short name for package names (default: the repo name)")
    parser.add_argument(
        "--monogram", help="1-2 letters for the logo square (default: first letter)"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    parser.add_argument("--dry-run", action="store_true", help="only show what would change")
    args = parser.parse_args(argv)
    args.slug = args.slug or args.repo.lower()

    problem = validate(args)
    if problem:
        print(f"ERROR: {problem}")
        return 2
    try:
        changed = apply_edits(args.root, build_edits(args), write=not args.dry_run)
    except ChangeError as error:
        print(f"ERROR: {error}\nNothing was changed.")
        return 1
    print(("Would change:" if args.dry_run else "Changed:") + "".join(f"\n  {f}" for f in changed))
    if not args.dry_run:
        print("\nNext: docs/NEW_PRODUCT.md, section 'After the script'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
