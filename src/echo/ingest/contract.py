from __future__ import annotations

from pathlib import Path

from echo.config import PACKAGE_DIR

REQUIRED_FILES = (
    "manifest.json",
    "baseline/transactions.csv",
    "baseline/accounts.csv",
    "history/sync_runs.csv",
    "history/sync_batches.csv",
    "history/sync_logs.csv",
    "pipeline/transform_versions.json",
    "evaluation/allowed/cases.json",
)

AGENT_FORBIDDEN_RELATIVE_PREFIXES = (
    "scenarios/",
    "evaluation/",
)


def package_path(*parts: str) -> Path:
    return PACKAGE_DIR.joinpath(*parts)


def validate_package(root: Path | None = None) -> list[str]:
    base = root or PACKAGE_DIR
    missing = []
    for rel in REQUIRED_FILES:
        if not (base / rel).is_file():
            missing.append(rel)
    return missing


def is_agent_forbidden(path: Path) -> bool:
    posix = path.resolve().as_posix()
    markers = (
        "/scenarios/",
        "/evaluation/",
        "patch.json",
        "answers.json",
        "/allowed/cases.json",
        "hidden",
    )
    return any(marker in posix for marker in markers)
