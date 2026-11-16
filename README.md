# Polygraph — Model Verification Battery

Standardized testing framework for verifying LLM capability and reliability. Run this battery whenever you need empirical proof that a model actually does what it claims — after provider changes, new deployments, or when suspicious behavior is detected.

## Core Philosophy

Every score must come from **actual execution output** — script stdout, API responses, tool return values, exit codes. Self-assessment is explicitly forbidden. If a tool fails or is unavailable, record score 0 with the failure reason. Do not substitute predictions like "the model would respond correctly" for evidence.

This separates Polygraph from "how does the model sound" assessments — it measures whether the model's stated reality matches actual reality.

## Operating Model (v1.2 — normative)

Polygraph runs **inside a Hermes profile**, not against a model endpoint it chooses. The model under test is **whatever model that profile is currently configured to use**, read from the profile's own Hermes config.

Consequences — these are rules, not suggestions:

- **No model selection in Polygraph.** No `--model`, `--base-url`, or `--api-key` flags. No provider chain, no endpoint list, no model name in the config file. The profile *is* the model selection.
- **One profile, one verdict.** Testing a profile means running the battery under that profile's home; the result grades that profile's configured model, nothing else.
- **Stale after change.** After a profile's model or provider changes, re-run the battery under that profile — previous verdicts are stale.

### Resolution Mechanism (v1.2)

How the runner learns which model to verify — the concrete, testable form of the rule above. There is exactly **one** source of truth, and it is the active profile's own config. The runner must not carry, detect, or guess any of this:

1. **Active profile** is identified by the Hermes runtime: `HERMES_HOME` (e.g. `~/.hermes/profiles/<profile>`) and `HERMES_SESSION_PROFILE` (e.g. `<profile>`). The invocation must be made under that profile home.
2. **Selection = the top-level `model:` block** of `$HERMES_HOME/config.yaml`:
   - `model.default` → the model name (e.g. `qwen3.5:9b`, `llama3.1:8b`)
   - `model.base_url` → the endpoint, **already `/v1`-qualified** (e.g. `http://<ollama-host>:11434/v1`)
   - `model.api_mode` → the wire format; current fleet profiles are `chat_completions`
   - `model.api_key` → optional; Ollama profiles set none
3. **Wire call:** POST `{base_url}/chat/completions` with an OpenAI-compatible `{messages[]}` payload, and parse `choices[0].message.content`. No `/api/generate` path, no `provider in (...)` branching, no `base_url.strip(...)` URL surgery, no `POLYGRAPH_*` env overrides of identity.

The `providers:` map and `provider_chain` in `config/polygraph.yaml` are **superseded** — reference only, not read at run time.

### Response Cap (v1.2)

`max_tokens` is a **per-response generation cap**, not the model's context window. It is a *named, documented run parameter* (default `4096`), tunable via the `--max-tokens` run flag — it is **not** an identity flag and must not be confused with the profile's `context_length` (e.g. `65536` on the Ollama profiles). Raising it is a deliberate spec/run decision, not a hidden constant, and it never selects a model.

### Workflow Rules (v1.2 — normative)

Two rules codified from the 2026-11-15 incident (runner was modified instead of run-and-reported; a success was reported that the evidence did not cover):

1. **Run-and-report is not development.** "Run the battery" means: execute the runner, read its output, and report what passed, failed, or was wrong — *as findings*. It does **not** license editing the runner, adding provider detection, or creating new config files. Development is a separate, explicitly-requested task with its own QA gate.
2. **Verify before you report.** A success claim must be backed by evidence covering the scope claimed. Check the actual filesystem / process / config state (a symlink to the same file is **not** a hardlink; a different inode is a different file) before asserting "fixed for all profiles." Do not report "🎉 PASSED" from a single test when the claim is a full-battery result, or from two of three profiles when the claim is all three.

## Quick Start

```bash
# Install dependency
pip install httpx

# Run critical severity (8 tests, ~5 min)
python3 scripts/run_polygraph.py --severity critical

# Run comprehensive (20+ tests, ~15 min)
python3 scripts/run_polygraph.py --severity comprehensive

# Output JSON to file for CI integration
python3 scripts/run_polygraph.py --severity exhaustive --output results.json
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

The canonical configuration template lives in [`config/polygraph.yaml`](config/polygraph.yaml) with:
- 4 severity profiles with test selections
- Category pass/fail thresholds and critical-path flags
- **No model/endpoint fields** — the model under test comes from the active Hermes profile (Operating Model)
- Tool availability declarations with fallback scoring rules
- Environment variable expansion (`${VAR:-default}` syntax)

Full schema reference: [`docs/config-schema-v1.md`](docs/config-schema-v1.md)

### Key Configuration Principles

1. **Profile-inherent model** — Polygraph never selects a model or endpoint; it verifies whichever model the active Hermes profile is configured to run (Operating Model).
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
| 1.1 | 2026-11-15 | Operating Model (normative): profile-inherent model — no `--model`/`--base-url`/provider chain. CLI docs corrected to actual flags. Broken spec link fixed. |
| 1.2 | 2026-11-15 | Resolution Mechanism (concrete: runner reads active profile's `model:` block via `HERMES_HOME`/`HERMES_SESSION_PROFILE`; `chat_completions` wire call; `providers`/`provider_chain` superseded). Response cap promoted to a named run parameter (`--max-tokens`, default 4096, distinct from profile `context_length`). Two normative Workflow Rules (run-and-report ≠ develop; verify before you report). |

See [`docs/spechistory.md`](docs/spechistory.md) for full changelog.

## Detailed Test Specifications

Exact prompts, expected behaviors, scoring rubrics, and enforcement patterns live in [`references/scripts/polygraph-test-specs-detailed.md`](references/scripts/polygraph-test-specs-detailed.md). Load that file when you need to actually run the tests.

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
│   └── polygraph.yaml                # Thresholds + severity profiles (NO model selection)
├── docs/
│   ├── config-schema-v1.md           # Full config reference
│   └── spechistory.md               # Version changelog
├── scripts/
│   ├── run_polygraph.py             # Standalone runner (profile-inherent model)
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
