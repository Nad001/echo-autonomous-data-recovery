# ECHO — Autonomous Data Recovery

**Every Error Leaves a Trace**

ECHO monitors data integrity after synchronization between trusted Finance records and an Analytics destination. It detects silent corruption, investigates discrepancies with an evidence-driven agent, applies only deterministic safety-approved repairs, and independently verifies the result.

This repository uses a synthetic dataset. It does not contain production data.

## Problem

A synchronization can complete successfully while destination values are wrong. ECHO separates transport success from data integrity and recovery safety.

## Solution

ECHO compares trusted source snapshots with destination records, gathers bounded diagnostic evidence, optionally asks OpenAI for a structured investigation, evaluates recovery with deterministic policy checks, and records the applied and independently verified outcome.

## How It Works

1. Reset an isolated runtime from the read-only package data and apply a selected fixture mutation.
2. Synchronize and compare source and destination records.
3. If discrepancies exist, expose schema, affected fields, values, history, and diagnostic results to the investigator through approved tools. Healthy runs skip investigation.
4. Validate the investigation report. The model proposes; deterministic safety policy authorizes or blocks.
5. Apply only eligible repairs, quarantine persistent pipeline defects when evidence supports it, or create a Human Review case.
6. Independently verify every changed field and persist the execution evidence for the UI and activity registry.

## Demonstrated Scenarios

The active registry contains exactly five reproducible fixtures:

- **Healthy Synchronization (SCENARIO-01):** 5,000 trusted records synchronize with zero discrepancies, repairs, or investigation.
- **Single Numerical Corruption (SCENARIO-02):** one amount is multiplied by 100 (the synthetic example is SAR 2,518.10 to SAR 251,810), then restored only when source authority and safety checks permit; verification checks the repair and unaffected records.
- **Partial Text Corruption (SCENARIO-03):** selected description fields receive controlled text mutations and are compared/restored from trusted source values when eligible.
- **Complete Data Corruption (SCENARIO-04):** a persistent transformation affects all 5,000 amounts; ECHO detects scope and separates pipeline quarantine from any recovery decision.
- **Human Approval Required (SCENARIO-05):** a destination-side override plus unavailable source trust makes automatic overwrite unsafe; ECHO preserves the destination value and records Human Review evidence.

The application also keeps legacy fixture files archived locally under `data/package/**/archive/legacy-60/`; they are not active scenarios.

## Technology Stack

- Python 3.12+
- Streamlit
- OpenAI Responses API (manual Live mode only; configured model defaults to `gpt-5.4`)
- SQLite runtime databases
- Pydantic structured-response validation
- pandas for fixture/history data
- pytest for local tests

## Installation and Running Locally

From the repository root:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
```

For a deterministic local demo, keep the defaults:

```bash
export ECHO_LLM=mock
streamlit run src/echo/ui/app.py
```

The app creates isolated runtime databases under `runtime/`. The package under `data/package/` is read-only. To run one backend fixture from the command line:

```bash
ECHO_LLM=mock python -m echo.cli SCENARIO-01
```

Live OpenAI is opt-in. Set `OPENAI_API_KEY` in the uncommitted `.env`, set `ECHO_LLM=openai`, and explicitly run a scenario in the UI. The key is never stored in this repository. Live calls may incur provider charges.

## Testing

Run the local suite without network access or OpenAI calls:

```bash
python -m pytest -q
```

The tests cover the five fixture paths, generic numerical/text evidence packaging, structured investigation parsing, mocked multi-tool completion and budget limits, API error handling, deterministic safety policy, recovery verification, persistence, UI execution guards, and proposed-versus-applied repair display. Mocked results are not live demonstrations.

## Current Limitations

- The data package is synthetic and intentionally small in scope: Finance-to-Analytics records and the schemas included here.
- Human Review persists the case and evidence for an operator. A complete approve/reject workflow is not implemented.
- Live OpenAI behavior depends on the configured key, account access, model availability, network, and provider limits. A failed Live request remains a failed investigation; it is never silently converted to Mock mode.
- The application is a local hackathon demonstration, not a production deployment or a claim of universal arbitrary-dataset support.

## Hackathon Information

**HUMAIN — Challenge 1: Agentic Recovery of a Failing System**

Suggested repository name: `echo-autonomous-data-recovery`

Suggested description: “ECHO is an AI-assisted data integrity and recovery system that detects silent corruption, investigates discrepancies, safely restores trusted values, and escalates uncertain cases for human review.”
