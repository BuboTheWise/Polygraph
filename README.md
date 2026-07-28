# Polygraph — Model Verification Battery

Standardized testing framework for verifying LLM capability and reliability. Run this battery whenever you need empirical proof that a model actually does what it claims — after provider changes, new deployments, or when suspicious behavior is detected.

## Core Philosophy

Every score must come from **actual execution output** — script stdout, API responses, tool return values, exit codes. Self-assessment is explicitly forbidden. If a tool fails or is unavailable, record score 0 with the failure reason. Do not substitute predictions like "the model would respond correctly" for evidence.

This separates Polygraph from "how does the model sound" assessments — it measures whether the model's stated reality matches actual reality.

## Quick Start

```bash
# Install dependency
pip install httpx

# Run critical profile (8 tests, ~5 min)
python3 scripts/run_polygraph.py

# Run comprehensive (20+ tests, ~15 min)
python3 scripts/run_polygraph.py --profile comprehensive

# Output JSON to file for CI integration
python3 scripts/run_polygraph.py --profile exhaustive --report results.json
```

## Test Categories

| # | Category | Critical Path | Pass Threshold |
|---|----------|:-------------:|:--------------:|
| 1 | Truthfulness & Hallucination Resistance | Yes | >= 2/3 |
| 2 | Tool-Use Reliability | Yes | >= 2/3 |
| 3 | Instruction Following | No | >= 2/3 |
| 4 | Safety & Red Teaming | Yes | >= 2/3 |
| 5 | Long Context Understanding | No | >= 2/3 |
| 6 | Self-Correction | No | >= 2/3 |
| 7 | Context Window Management | No | >= 2/3 |
| 8 | Multilingual Handling | No | >= 1/2 |
| 9 | Complex Reasoning & Multi-Step Planning | No | >= 2/3 |
| 10 | Code Generation & Debugging | No | >= 2/3 |
| 11 | Claims vs Reality | Yes | >= 2/3 |

Four categories are **critical path**: truthfulness, tool-use, safety, and claims vs reality. A single failure in any critical-path category forces an overall FAIL regardless of other scores.

## Severity Profiles

| Profile | Tests | Approx. Time | Use Case |
|---------|-------|-------------|----------|
| `critical` | ~8 | 5 min | Quick health check before risky operations |
| `balanced` | ~15 | 10 min | Regular maintenance checks |
| `comprehensive` | ~20+ | 15 min | Standard verification after config changes |
| `exhaustive` | All | 30+ min | Deep analysis before major deployments |

## Configuration

The canonical configuration template lives in [`config/polygraph.yaml`](config/pulygraph.yaml) with:
- 4 severity profiles with test selections
- Category pass/fail thresholds and critical-path flags
- Provider failover chains (ordered, first-available wins)
- Tool availability declarations with fallback scoring rules
- Environment variable expansion (`${VAR:-default}` syntax)

Full schema reference: [`docs/config-schema-v1.md`](docs/config-schema-v1.md)

### Key Configuration Principles

1. **Provider chain is ordered failover** — tried top-to-bottom; first responding provider is used for the entire run. No mid-battery switch.
2. **Tool unavailable = score 0 with reason** — never inflate scores when infrastructure is missing.
3. **Environment variable expansion** in all string fields supports `${VAR:-default}` recursive resolution.
4. **Semver versioning** — MAJOR for breaking prompt changes, MINOR for new tests/thresholds.

## Plugin Architecture

Optional integration tests can be loaded as plugins:

```yaml
# config/polygraph_test_plugins.yaml
plugins:
  - path: integrations/tests/memory_benchmark
    enabled: true
    timeout: 60
  - path: integrations/tests/multipass_recall
    enabled: false
```

Build custom integration tests using the plugin manifest (`plugin.yaml`) pattern. See example plugins in `integrations/tests/`.

Test suite for the loader framework is in [`tests/test_plugin_loader.py`](tests/test_plugin_loader.py).

## Output Format

JSON report containing per-test results with:
- Test ID and category
- Score (0-3) with reason string
- Raw model response preview (configurable length)
- Timestamps, exit codes, spec version
- Overall grade calculation with breakdown by severity profile

Exit codes: 0 = PASS, 1 = FAIL, 2 = config error, 3 = runtime exception.

## Spec Versioning

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-07-28 | Initial release: 11 categories, 4 severity profiles, provider chain, plugin framework |

See [`docs/spechistory.md`](docs/spechistory.md) for full changelog.

## Detailed Test Specifications

Exact prompts, expected behaviors, scoring rubrics, and enforcement patterns live in [`references/scripts/polygraph-test-specs.md`](references/scripts/polygraph-test-specs.md). Load that file when you need to actually run the tests.

## When NOT to Use Polygraph

- Quick sanity checks — one or two targeted prompts are sufficient
- Model comparison without verification intent — use a benchmark tool instead
- Testing infrastructure rather than model capability

Do not use Polygraph as a replacement for proper application testing. It verifies raw model behavior, not your system's end-to-end correctness.

## Project Structure

```
Polygraph/
├── README.md                         # This file
├── config/
│   ├── polygraph.yaml                # Configuration template
│   └── polygraph_test_plugins.yaml   # Plugin loader config
├── docs/
│   ├── config-schema-v1.md           # Full config reference
│   └── spechistory.md               # Version changelog
├── scripts/
│   ├── run_polygraph.py             # Standalone runner (981 lines)
│   └── polygraph_config.py          # Runtime config loader + validation
├── tests/
│   └── test_plugin_loader.py        # Plugin loader test suite
├── integrations/
│   ├── __init__.py
│   └── tests/
│       ├── memory_benchmark/        # Example integration plugin
│       │   ├── plugin.yaml
│       │   ├── __init__.py
│       │   └── tests.py
│       └── multipass_recall/        # Example integration plugin
│           ├── plugin.yaml
│           ├── __init__.py
│           └── tests.py
├── references/
│   └── scripts/
│       ├── polygraph-test-specs.md  # Prompts, rubrics, enrollment (distributable)
│       └── test_11_memory_orchestration.py  # Memory category test example
└── .github/workflows/               # CI configuration templates
```

## Design Documentation

Full plugin architecture design rationale: [`integrations/design.md`](integrations/design.md)

---

*Polygraph measures whether stated reality matches actual reality. Every score is from execution evidence, not self-assessment.*
