from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# The project-root .env is the explicit local configuration for ECHO. Use it
# as the source of truth so an unrelated inherited shell variable cannot cause
# the dashboard to authenticate with a different credential.
load_dotenv(PROJECT_ROOT / ".env", override=True)

PACKAGE_DIR = PROJECT_ROOT / "data" / "package"
RUNTIME_DIR = Path(os.getenv("ECHO_RUNTIME_DIR") or PROJECT_ROOT / "runtime")
HIDDEN_DIR = PROJECT_ROOT / "evaluation" / "hidden"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("ECHO_OPENAI_MODEL", "gpt-5.4")
MAX_TOOL_CALLS = int(os.getenv("ECHO_MAX_TOOL_CALLS", "8"))
MAX_INPUT_TOKENS = int(os.getenv("ECHO_MAX_INPUT_TOKENS", "12000"))
MAX_OUTPUT_TOKENS = int(os.getenv("ECHO_MAX_OUTPUT_TOKENS", "2000"))
MAX_ESTIMATED_USD = float(os.getenv("ECHO_MAX_ESTIMATED_USD", "0.10"))
MAX_SECONDS = float(os.getenv("ECHO_MAX_SECONDS", "90"))
MIN_INVESTIGATION_CONFIDENCE = float(os.getenv("ECHO_MIN_INVESTIGATION_CONFIDENCE", "0.60"))
LLM_MODE = os.getenv("ECHO_LLM", "mock")
SAMPLE_LIMIT = 20
REPAIR_ID_CAP = 500
DEFAULT_DEMO_CASE = os.getenv("ECHO_DEMO_CASE", "SCENARIO-01")
PIPELINE_ID = "finance-to-analytics"


def ensure_runtime_dir() -> Path:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    return RUNTIME_DIR


def finance_db_path() -> Path:
    return ensure_runtime_dir() / "finance.sqlite"


def analytics_db_path() -> Path:
    return ensure_runtime_dir() / "analytics.sqlite"


def echo_db_path() -> Path:
    return ensure_runtime_dir() / "echo.sqlite"
