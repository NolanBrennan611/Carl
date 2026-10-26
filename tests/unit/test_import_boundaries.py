"""Business-logic packages must never import discord (docs/architecture.md section 3)."""

import ast
from pathlib import Path

SRC = Path(__file__).parents[2] / "src" / "carl"
FORBIDDEN_PACKAGES = ["domain", "services", "repositories", "scheduler", "db"]
FORBIDDEN_TOP_LEVEL_FILES = ["app.py", "config.py", "clock.py", "ports.py"]


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def python_files() -> list[Path]:
    files = [f for pkg in FORBIDDEN_PACKAGES for f in (SRC / pkg).rglob("*.py")]
    files += [SRC / name for name in FORBIDDEN_TOP_LEVEL_FILES if (SRC / name).exists()]
    return files


def test_there_are_files_to_check():
    assert len(python_files()) > 10


def test_no_discord_imports_outside_the_adapter_layer():
    offenders = []
    for path in python_files():
        for module in imported_modules(path):
            if module == "discord" or module.startswith(("discord.", "carl.discord_ui")):
                offenders.append(f"{path.relative_to(SRC)} imports {module}")
    assert offenders == []


def test_core_never_reads_the_wall_clock_directly():
    banned = ("datetime.now(", "date.today(", "time.time(", "datetime.utcnow(")
    offenders = []
    for path in SRC.rglob("*.py"):
        if path.name in {"clock.py", "cli.py"}:  # clock.py is the port; cli.py names a backup file
            continue
        text = path.read_text(encoding="utf-8")
        offenders += [f"{path.relative_to(SRC)}: {b}" for b in banned if b in text]
    assert offenders == []
