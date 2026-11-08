---
name: polygraph
description: "Model verification battery: empirical capability checks from execution evidence."
version: 0.1.0
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

# Runner default severity: comprehensive (~20+ tests, ~15 min)
python3 scripts/run_polygraph.py \
  --model <model-name> \
  --base-url <openai-compatible-endpoint> \
  --api-key <key> \
  --output polygraph-report.json

# Severity levels: critical (~8 tests), balanced (~15), comprehensive (default), exhaustive (all)
python3 scripts/run_polygraph.py --severity critical --model <m> --base-url <url>

# Specific tests only
python3 scripts/run_polygraph.py --tests 1A,3B,11D --model <m> --base-url <url>
```

Flags: `--severity`, `--model`, `--base-url`, `--api-key` (defaults to `$OPENAI_API_KEY`), `--provider`, `--output` (JSON report path), `--no-tools` (skip tool-requiring tests), `--tests` (comma-separated test IDs).

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
- Provider chain in config is ordered failover (first responding provider wins, no mid-battery switching); the CLI `--base-url`/`--model` override it directly.
