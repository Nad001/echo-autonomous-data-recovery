# ECHO synthetic dataset v1.0

**Synthetic only.** All transactions and accounts are fabricated. Currency is SAR, `amount_halalas` is an integer minor-unit value.

## Installation
Extract the **contents** of `ECHO_data_package.zip` into `~/Projects/echo/data/package/`. You should see `manifest.json` directly inside `package/`, not another nested `ECHO_data_package` folder.

## Layout
- `baseline/transactions.csv`: 5,000 source-of-truth rows; unique `record_id`; integer amounts.
- `baseline/accounts.csv`: account dimension.
- `history/`: 20 healthy sync runs, 10 batches each, plus execution logs.
- `pipeline/transform_versions.json`: versioned transformation specifications.
- `scenarios/SCENARIO-01..05/patch.json`: the five active compact setup mutations; **fixture loader only**.
- `alerts/SCENARIO-01..05.json`: incident payloads to deliver to the agent/worker.
- `evaluation/allowed/cases.json`: five local evaluation descriptors.
- `scenarios/archive/legacy-60/` and `alerts/archive/legacy-60/`: archived legacy fixtures, not active scenarios.

## IMPORTANT: No answer leakage
Do NOT expose `scenarios/*/patch.json`, `evaluation/allowed/cases.json` or their metadata to the LLM. They are simulator/runner setup inputs, not investigation evidence. The agent should receive only incident alerts and runtime source/destination/history/configuration through approved diagnostic tools. `scenario_setup.first_modified_batch_seq` is fixture setup metadata and must NEVER be returned to the agent. The separate hidden ZIP belongs outside the project and must never be mounted in the agent or worker process.

## Scenario semantics
SCENARIO-01 is a healthy baseline. SCENARIO-02 is one-off amount scaling corruption, eligible for selective verified recovery when source versions are trusted. SCENARIO-03 is controlled text corruption. SCENARIO-04 is a persistent transform defect requiring quarantine analysis before recovery or escalation. SCENARIO-05 is a destination version conflict with unavailable trusted snapshots; never overwrite conflicted records.

`destination_mutations` are applied in array order. For C, first corrupt amount then advance destination version for the same records. This represents a conflict state; do not interpret the mutation patch itself as evidence that an actual authorized value is correct. Loader must preserve version/audit evidence and require escalation.

**History limitation:** baseline history contains 20 healthy runs. Scenario setup specifies where an incident begins in the fixture; the loader must construct observable batch logs/record snapshots so that an investigator can infer onset. Do not pass setup metadata to the agent or pretend historical evidence exists if not materialized.

## Evaluation
The package contains only local descriptors and no hidden answers. Mocked tests and live model results must be reported separately.

## Reset
Always clone baseline into `runtime/` and apply a patch to the clone. Never modify package originals.
