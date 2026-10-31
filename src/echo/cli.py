from __future__ import annotations

import argparse
import json

from echo.config import DEFAULT_DEMO_CASE
from echo.ingest.scenarios import load_case
from echo.worker.main import process_one


def reset_demo() -> None:
    parser = argparse.ArgumentParser(description="Reset and run an ECHO demo case")
    parser.add_argument("case_id", nargs="?", default=DEFAULT_DEMO_CASE)
    args = parser.parse_args()
    setup = load_case(args.case_id)
    result = process_one()
    print(json.dumps({"setup": setup, "result": result}, indent=2))


if __name__ == "__main__":
    reset_demo()
