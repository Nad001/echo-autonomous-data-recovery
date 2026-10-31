# ECHO — Autonomous Data Recovery

**Every Error Leaves a Trace.**

## Overview

Successful synchronization does not guarantee correct data. Silent corruption can change values while the system reports that the transfer completed.

ECHO is a general-purpose AI-assisted data integrity and recovery system. It compares trusted and destination data, explains discrepancies, and supports safe recovery when the evidence allows it.

Finance is the example data flow used for this hackathon demonstration, not ECHO's only application.

## How It Works

**Detect** → Compare synchronized data and identify what changed.

**AI Investigate** → Use the available evidence to explain the problem, likely cause, and uncertainty.

**Safe Recovery or Human Review** → Apply only independently authorized corrections. Block unsafe or uncertain changes for human review.

**Verify** → Check the actual result independently and preserve the evidence.

## Example Scenarios

- Healthy data with no recovery needed.
- Incorrect numerical values that can be safely restored from trusted data.
- Partial text corruption, such as truncation or unexpected replacements.
- Complete data corruption requiring broad investigation and safety checks.
- Possible manual overrides or conflicting updates that may require human review.

## Technology Stack

- Python
- Streamlit
- OpenAI Responses API
- SQLite
- Pydantic
- pandas
- pytest

## Current Limitations

The included data and workflows demonstrate supported integrity and recovery patterns; ECHO is not presented as universal support for every possible dataset or storage system.

Human Review currently preserves the case and supporting evidence for an operator. A complete approval and rejection workflow is not implemented.

Live AI investigations require an explicitly configured OpenAI API key and available model access. Failed model requests are not silently treated as successful investigations.

## Hackathon Information

**HUMAIN — Challenge 1: Agentic Recovery of a Failing System**
