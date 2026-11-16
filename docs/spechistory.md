# Polygraph Specification Version History

This file tracks every change to test prompts, scoring rubrics, categories, and profiles.
Two reports are directly comparable only if they share the same spec version and profile.

---

## v1.0 — 2026-07-28 (Initial Release)

**Author:** orchestrator/executor via Kanban

**What changed from scratch:**

- Defined the configuration schema in `config/polygraph.yaml` with all sections:
  spec metadata, profiles, categories, provider chain, tool fallbacks, paths, and reports.
- 11 test categories formally documented with pass/fail thresholds (0-3 scale).
  Categories 1 (Truthfulness), 2 (Tool-Use), 4 (Safety), and 11 (Claims vs Reality) marked as critical_path — a.FAIL in any of these forces overall FAIL.
- 4 severity profiles established: critical (8 tests), balanced (13 tests), comprehensive (20 tests), exhaustive (21 tests).
- Provider chain supports ordered failover with env var expansion for base URLs and API keys.
- Tool availability declared per-tool with mandatory `score_zero` fallback — unavailable tools never inflate scores.
- Report embeds spec version by default so non-comparable results are flaggable.
- Configuration loader (`polygraph_config.py`) validates all fields, raises `ConfigError` on malformed YAML, expands `${VAR:-default}` patterns recursively.
- Backward compatibility policy codified: additive keys = MINOR, removed/renamed = MAJOR bump.

**Full schema reference:** see `docs/config-schema-v1.md`.

---

## Version Numbering Convention

| Component | Bump when… | Example trigger |
|-----------|------------|-----------------|
| **MAJOR** | Breaking changes to existing test prompts, rubrics fundamentally changed, categories merged or split, profile IDs removed | Test 1A reworded from "non-existent paper" to "real paper with wrong date" |
| **MINOR** | New tests added without removing old ones, thresholds adjusted, category descriptions clarified, new profile added | Tests 12A-12C (new domain), threshold for Category 8 lowered from 2 to 1 |
| **PATCH** | Documentation-only changes to this file or the schema reference. Test behavior unchanged. Typos fixed. | Clarified "score_zero" description in config doc |

Reports embed the version string so any two reports can detect a version mismatch before comparing results. If `include_spec_version` is set to `true` in the reports config (the default), the header shows:

```
POLYGRAPH VERIFICATION REPORT
Spec Version: 1.0
Profile: comprehensive
...
```

---

## v1.1 — 2026-11-15 (Operating Model: Profile-Inherent Model)

**Author:** primary dev agent, on the owner's directive — normative, takes precedence over any runner implementation

**What changed:**

- **Polygraph runs inside a Hermes profile.** The model under test is the profile's own configured model, discovered from the profile's Hermes config (`~/.hermes/profiles/<profile>/config.yaml` → `model.default`, `provider`, `base_url`). The invocation must run under the correct profile home.
- **Polygraph has no model selection of its own:** no `--model`, `--base-url`, or `--api-key` CLI flags; no provider chain; no model name in the config file. `provider_chain` in `config/polygraph.yaml` is **superseded** — kept for reference only, not normative.
- **CLI documentation corrected** to match the actual runner flags: `--severity`, `--tests`, `--output`, `--no-tools` (the docs previously advertised `--profile`/`--report` which do not exist).
- **Broken link fixed:** detailed test specs live in `references/scripts/polygraph-test-specs-detailed.md`.
- **Enforcement rule:** a verdict grades the model the *profile* is configured to run. After any profile model/provider change, the battery must be re-run under that profile; prior verdicts are stale.

**Why:** v1.0 implied the runner chooses a model endpoint (provider chain naming `qwen3.6:27b`, which does not exist on the box that runs it). That is a foreign notion to this fleet: a Hermes profile **is** the model selection. Polygraph's job is to verify the model a profile is running — not to pick one. This is the single most important rule in the spec: any PR that adds model/endpoint selection to the runner or config is a spec violation until this entry is explicitly revised.

**Implementation status:** runner not yet conformant — `run_polygraph.py` still carries `--model`/`--base-url`/provider-detection logic. Conformance is the assigned dev's next fix pass; QA gates the merge.

---

## v1.2 — 2026-11-15 (Resolution Mechanism, Response Cap, Workflow Rules)

**Author:** primary dev agent, on the owner's directive — spec-first, normative, takes precedence over any runner implementation

**What changed:**

- **Resolution Mechanism (concrete).** v1.1 said the runner reads the profile's config; v1.2 names exactly how, so it is testable and not guessable:
  1. Active profile = `HERMES_HOME` + `HERMES_SESSION_PROFILE` (set by the Hermes runtime; the invocation must run under that profile home).
  2. Selection = the **top-level `model:` block** of `$HERMES_HOME/config.yaml`: `model.default` (name), `model.base_url` (endpoint, already `/v1`-qualified), `model.api_mode` (current fleet: `chat_completions`), `model.api_key` (optional).
  3. Wire call = POST `{base_url}/chat/completions` with an OpenAI-compatible `{messages[]}` payload; parse `choices[0].message.content`.
  - Prohibited at run time: `--model`/`--base-url`/`--api-key` identity flags, `provider in (...)` branching, `base_url.strip(...)` URL surgery, `POLYGRAPH_*` env overrides of identity. `providers:` map and `provider_chain` are **superseded** — reference only.
- **Response cap.** `max_tokens` is a **named, documented run parameter** (`--max-tokens`, default `4096`) — a per-response generation cap, distinct from the profile's `context_length` (e.g. `65536`). It is tunable by decision and is **not** an identity selection. This removes the previously hidden `4096` magic constant from the spec surface.
- **Workflow Rules (normative).** Codified from the 2026-11-15 incident:
  1. **Run-and-report is not development.** "Run the battery" = execute + report findings. It does not license editing the runner, adding provider detection, or creating new config files. Development is a separate, explicitly-requested task with its own QA gate.
  2. **Verify before you report.** A success claim must be backed by evidence covering the scope claimed. A symlink to the same file is not a hardlink; a different inode is a different file. Do not report a full-battery pass from one test, or "all profiles" from two of three.

**Why:** v1.1 stated the model is profile-inherent but left the mechanism underspecified, so the runner (and a subsequent edit) reintroduced provider/endpoint selection and a hidden token cap. v1.2 makes the single source of truth concrete and testable, and closes the two process gaps (scope drift; over-claimed success) that the incident exposed.

**Enforcement:** any PR that adds model/endpoint/provider selection to the runner or config, or that reads identity from `POLYGRAPH_*` env / `providers` / `provider_chain`, is a spec violation until this entry is explicitly revised.

