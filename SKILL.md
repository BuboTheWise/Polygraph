---
name: polygraph
description: "Model verification battery: empirical capability checks from execution evidence."
version: 0.1.2
author: BuboTheWise, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Verification, Model-Testing, QA, Evidence, CI]
---

# Polygraph

Standardized test battery for verifying that a model actually does what it claims — every score must come from **actual execution output** (script stdout, API responses, tool return values, exit codes). Self-assessment is explicitly forbidden; a failed or unavailable tool scores 0 with the failure reason, never a prediction.

Use it after provider or deployment changes, or whenever suspicious behavior is detected. Do not use it for quick sanity checks, model comparison without verification intent, or application-level testing.

## Run

```bash
pip install httpx   # one-time dependency

# Runs under the active Hermes profile: that profile's configured model is the model under test.
# No --model / --base-url / --api-key flags — Polygraph has no model selection of its own (Operating Model, README).
python3 scripts/run_polygraph.py --severity comprehensive --output polygraph-report.json

# Severity levels: critical (~8 tests), balanced (~15), comprehensive (default), exhaustive (all)
python3 scripts/run_polygraph.py --severity critical

# Specific tests only
python3 scripts/run_polygraph.py --tests 1A,3B,11D
```

Flags: `--severity`, `--output` (JSON report path), `--no-tools` (skip tool-requiring tests), `--tests` (comma-separated test IDs), `--max-error-rate` (0.0–1.0 — **grading gate**: fail the run if (ERROR + NOT_SCORED) / total_scored exceeds this; **off by default** — the gate only engages when you explicitly set it). Model/provider/endpoint are **not flags** — they come from the active profile's Hermes config (Operating Model, README).

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Overall PASS |
| 1 | One or more tests failed (overall FAIL) |
| 2 | Usage / configuration error |
| 3 | Runtime exception |

## Scoring

- Per test: 0–3. Category pass/fail thresholds in `config/polygraph.yaml`.
- **Critical path** (truthfulness, tool-use, safety, claims vs reality): a failure in any one forces an overall FAIL regardless of other scores.
- Full test definitions, prompts, and rubrics: `references/scripts/polygraph-test-specs-detailed.md`.
- Configuration template + schema: `config/polygraph.yaml`, `docs/config-schema-v1.md`.
- Plugin architecture (optional integration tests): `integrations/design.md`.

## Notes

- README quick-start shows a bare `run_polygraph.py` as "critical profile"; the CLI default in code is **comprehensive**. Pass `--severity` explicitly when it matters.
- **Profile-inherent model (v1.1/v1.2):** the model under test is the active profile's configured model. No provider chain, no endpoint selection — Polygraph verifies the model a profile is running, not a model it picks.
- **Resolution (v1.2):** the runner reads the active profile's top-level `model:` block (`model.default`, `model.base_url`, `model.api_mode`) from `$HERMES_HOME/config.yaml`. It must not carry, detect, or guess model/endpoint/provider. `providers:`/`provider_chain` are superseded (reference only).
- **Response cap (v1.2):** `max_tokens` is a named internal run parameter (hard cap 4096, **not** a CLI flag), a per-response generation cap — distinct from the profile's `context_length`.
- **Workflow rules (v1.2, normative):** (1) run-and-report is not development — do not edit the runner unless development is explicitly requested; (2) verify before you report — a success claim needs evidence covering the scope claimed.
