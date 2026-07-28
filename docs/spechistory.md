# Polygraph Specification Version History

This file tracks every change to test prompts, scoring rubrics, categories, and profiles.
Two reports are directly comparable only if they share the same spec version and profile.

---

## v1.0 — 2026-07-28 (Initial Release)

**Author:** Bubo (orchestrator/executor via Kanban)

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
