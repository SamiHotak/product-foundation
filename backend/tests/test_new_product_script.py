"""scripts/new_product.py: renames the template safely, or changes nothing."""

import importlib.util
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "new_product.py"
FILES = [
    "frontend/config/product.ts",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/tests/e2e/design-system.spec.ts",
    "backend/app/core/config.py",
    "deploy/docker-compose.dev.yml",
    "deploy/.env.example",
    "deploy/server-setup.md",
]

pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="repository root is not available")


@pytest.fixture(scope="module")
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("new_product", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["new_product"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def copy(tmp_path: Path) -> Path:
    for name in FILES:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / name, target)
    return tmp_path


def run(script: ModuleType, root: Path, *extra: str, name: str = "AskDocs") -> int:
    code: int = script.main(
        [
            "--name", name,
            "--tagline", 'Ask "questions" about your documents.',
            "--accent", "#0F766E",
            "--accent-dark", "#5EEAD4",
            "--github-user", "My-User",
            "--repo", "AskDocs",
            "--root", str(root),
            *extra,
        ]
    )  # fmt: skip
    return code


def test_dry_run_changes_nothing(script: ModuleType, copy: Path) -> None:
    before = {f: (copy / f).read_bytes() for f in FILES}
    assert run(script, copy, "--dry-run") == 0
    assert {f: (copy / f).read_bytes() for f in FILES} == before


def test_renames_everything(script: ModuleType, copy: Path) -> None:
    assert run(script, copy) == 0
    product = (copy / "frontend/config/product.ts").read_text()
    assert 'name: "AskDocs",' in product
    assert 'tagline: "Ask \\"questions\\" about your documents.",' in product
    assert 'monogram: "A",' in product
    assert 'accent: { light: "#0F766E", dark: "#5EEAD4" }' in product
    assert "APP_NAME: AskDocs " in (copy / "deploy/docker-compose.dev.yml").read_text()
    env = (copy / "deploy/.env.example").read_text()
    assert "APP_NAME=AskDocs\n" in env
    assert "IMAGE_PREFIX=ghcr.io/my-user/askdocs\n" in env  # GitHub wants it lowercase
    assert 'app_name: str = "AskDocs"' in (copy / "backend/app/core/config.py").read_text()
    assert '"name": "askdocs-frontend"' in (copy / "frontend/package.json").read_text()
    assert (copy / "frontend/package-lock.json").read_text().count("askdocs-frontend") == 2
    spec = (copy / "frontend/tests/e2e/design-system.spec.ts").read_text()
    assert "Dashboard · AskDocs/" in spec
    assert 'name: "AskDocs home"' in spec
    for name in FILES:
        assert "product-foundation" not in (copy / name).read_text()


def test_a_quote_as_monogram_cannot_break_the_file(script: ModuleType, copy: Path) -> None:
    assert run(script, copy, "--monogram", '"') == 0
    assert 'monogram: "\\"",' in (copy / "frontend/config/product.ts").read_text()


def test_a_name_that_starts_with_a_digit_works(script: ModuleType, copy: Path) -> None:
    assert run(script, copy, name="3D Counter") == 0
    assert "APP_NAME: 3D Counter " in (copy / "deploy/docker-compose.dev.yml").read_text()
    assert 'monogram: "3",' in (copy / "frontend/config/product.ts").read_text()


def test_second_run_refuses_and_changes_nothing(script: ModuleType, copy: Path) -> None:
    assert run(script, copy) == 0
    after_first = {f: (copy / f).read_bytes() for f in FILES}
    assert run(script, copy, name="Other") == 1
    assert {f: (copy / f).read_bytes() for f in FILES} == after_first


def test_a_missing_file_changes_nothing(script: ModuleType, copy: Path) -> None:
    (copy / "backend/app/core/config.py").unlink()
    before = {f: (copy / f).read_bytes() for f in FILES if (copy / f).exists()}
    assert run(script, copy) == 1  # config.py is checked after product.ts was prepared
    assert {f: (copy / f).read_bytes() for f in before} == before


@pytest.mark.parametrize(
    "bad",
    [
        ["--accent", "red"],
        ["--accent-dark", "#12345"],
        ["--repo", "has space"],
        ["--github-user=-bad"],
        ["--slug", "Big Letters"],
        ["--monogram", "ABC"],
    ],
)
def test_bad_input_is_refused(script: ModuleType, copy: Path, bad: list[str]) -> None:
    before = (copy / "frontend/config/product.ts").read_bytes()
    assert run(script, copy, *bad) == 2  # argparse keeps the LAST value given
    assert (copy / "frontend/config/product.ts").read_bytes() == before
