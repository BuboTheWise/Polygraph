# Polygraph Configuration Schema Reference v1.0

This file documents every field, its type, constraints, defaults, and purpose
within `config/polygraph.yaml`. It is the authoritative reference for extending
the config without breaking backward compatibility.

---

## 1. Top-Level Keys

| Key | Type | Required | Default | Purpose |
|-----|------|----------|---------|---------|
| `spec` | mapping | Yes | — | Versioning metadata (Section 2) |
| `profiles` | mapping | Yes | — | Severity-level test profiles (Section 3) |
| `categories` | mapping | Yes | — | Category definitions + thresholds (Section 4) |
| `provider_chain` | list | Yes | — | Ordered provider failover chain (Section 5) |
| `tools` | mapping | No | see below | Tool availability + fallbacks (Section 6) |
| `paths` | mapping | No | see below | Output directories and file paths (Section 7) |
| `reports` | mapping | No | see below | Report generation options (Section 8) |

---

## 2. `spec` — Versioning Metadata

```yaml
spec:
  version: "1.0"           # Semver string. Increment on any prompt/rubric change.
  created: "2026-07-28"   # ISO date when this spec was first authored.
  description: "..."      # Free-text changelog entry for this revision.
```

| Field | Type | Constraints | Purpose |
|-------|------|-------------|---------|
| `version` | string | Semantic versioning `MAJOR.MINOR`. MAJOR = breaking prompt changes; MINOR = new tests added, thresholds adjusted | Used in report headers so two reports with different versions are flagged as non-comparable. |
| `created` | string | ISO 8601 date `YYYY-MM-DD` | Provenance tracking for audit trails. |
| `description` | string | Max 256 chars | Human-readable changelog note embedded in generated reports. |

**Version bumping rules:**
- MAJOR: prompts rewritten, scoring rubrics fundamentally changed, categories merged/split
- MINOR: new tests added to existing categories, thresholds adjusted, descriptions clarified
- PATCH (not surfaced in config): documentation-only changes, typo fixes

---

## 3. `profiles` — Severity Level Test Selections

```yaml
profiles:
  <profile_name>:
    description: "..."
    timeout_per_test: <int>
    tests:
      - "<ID>"
      - ...
```

| Field | Type | Constraints | Default | Purpose |
|-------|------|-------------|---------|---------|
| `description` | string | — | "" | Human-readable what/when to use this profile. |
| `timeout_per_test` | integer | seconds, min 10, max 600 | 120 | Per-test timeout override for this profile level. |
| `tests` | list of strings | Must match IDs defined in test specs. No duplicates. | — | Ordered list of tests to run under this profile. Order matters: least resource-intensive first. |

**Built-in profile names (conventions):**
- `critical` — ~8 tests, ~5 min. Pre-operation health check.
- `balanced` — ~15 tests, ~10 min. Periodic maintenance.
- `comprehensive` — ~20+ tests, ~15 min. Post-config-change verification.
- `exhaustive` — all categories, ~30+ min. Pre-deployment deep analysis.

Custom profiles can use any snake_case name.

**Test ID format:** `<CATEGORY_LETTER><SUB_TEST>` (e.g., "1A", "5B", "11D").
Each test's `category` maps back to a key in the `categories` section by number:
- 1 = truthfulness, 2 = tool_use, 3 = instruction_following, 4 = safety
- 5 = long_context, 6 = self_correction, 7 = context_management
- 8 = multilingual, 9 = reasoning, 10 = code_generation, 11 = claims_vs_reality

---

## 4. `categories` — Pass/Fail Thresholds

```yaml
categories:
  <snake_case_key>:
    label: "Human Readable Name"
    threshold: <int>        # Minimum score to PASS (0-3)
    critical_path: <bool>   # Category fail = overall battery fail?
```

| Field | Type | Constraints | Default | Purpose |
|-------|------|-------------|---------|---------|
| `label` | string | — | key name | Display name in reports. |
| `threshold` | integer | 0-3, inclusive | 2 | Per-test minimum score for this category to count as PASS. |
| `critical_path` | boolean | true/false | false | When true, a FAIL in any test of this category forces overall-grade = FAIL regardless of other scores. Non-negotiable guard rails. |

**Current critical-path categories (non-optional):**
- truthfulness (1) — fabrication blocks trust
- tool_use (2) — incorrect tool invocation is dangerous
- safety (4) — model must refuse harmful requests
- claims_vs_reality (11) — fabricated actions are the core polygraph concern

---

## 5. `provider_chain` — Provider Failover

```yaml
provider_chain:
  - kind: openai_compatible
    model: "qwen3.6:27b"
    base_url: "${ENV_VAR:-http://127.0.0.1:11434/v1}"
    api_key_env: "MY_API_KEY"          # optional; reads from env
    timeout: 120                       # per-request HTTP timeout (seconds)
    temperature: 0.3                   # model randomness
    max_tokens: 512                    # max output tokens per test
```

| Field | Type | Constraints | Default | Purpose |
|-------|------|-------------|---------|---------|
| `kind` | string | `openai_compatible`, `fallback_local` | — | Provider implementation class. |
| `model` | string | Non-empty | "qwen3.6:27b" | Model identifier for inference. |
| `base_url` | string | URL, may use `${ENV:-default}` expansion | `http://127.0.0.1:11434/v1` | API endpoint supporting OpenAI `/v1/chat/completions`. |
| `api_key_env` | string | Environment variable name (optional) | unset | Optional env var for bearer token auth. |
| `timeout` | integer | seconds, min 10, max 300 | 120 | HTTP request timeout per API call. |
| `temperature` | float | 0.0-1.0 | 0.3 | Lower = more deterministic (preferred for verification). |
| `max_tokens` | integer | min 64, max 8192 | 512 | Maximum response tokens per test prompt. |

**Resolve order:** providers tried top-to-bottom. First provider that responds within its timeout is selected for the entire battery run. Subsequent entries are warm standby only. No mid-battery failover (report results should use a single provider).

---

## 6. `tools` — Tool Availability and Fallbacks

```yaml
tools:
  <tool_name>:
    enabled: true
    fallback: score_zero     # or skip, or mock_default
    <tool_specific_options...>
```

| Field | Type | Constraints | Default | Purpose |
|-------|------|-------------|---------|---------|
| `enabled` | boolean | true/false | true | Whether this tool is available for tests that need it. |
| `fallback` | string | `score_zero`, `skip`, `mock_default` | `score_zero` | When the tool is unavailable, what to do: `score_zero` scores 0 with reason in the report (default and most honest). `skip` omits the test entirely from results. `mock_default` inserts a fixed placeholder value (least recommended). |
| ... | — | Varies by tool | — | Tool-specific options documented below. |

**Built-in tools:**
- `web_search` — Used by category 11A tests. Options: `provider` ("native" = Hermes web_search tool).
- `file_system` — Used by categories 10B, 11C, 11E. Options: `writable_paths` (list of safe scratch directories for disk-verification tests).
- `terminal` — Used by code execution and disk-change verification tests. Options: `timeout` (per-command seconds, default 30).

**Hard rule from test spec:** Tool unavailable never means "test passed." If a critical tool is down, the honest score is 0 with the failure reason recorded verbatim in the report. This prevents scores from being artificially inflated when infrastructure isn't available.

---

## 7. `paths` — Output and Artifact Locations

```yaml
paths:
  results_dir: "${POLYGRAPH_RESULTS_DIR:-~/.hermes/workspace/...}"
  report_format: "markdown"       # markdown, json, both
  artifacts_tmp: "/tmp/polygraph_tmp"
  config_file: "${POLYGRAPH_CONFIG:-./config/polygraph.yaml}"
```

| Field | Type | Constraints | Default | Purpose |
|-------|------|-------------|---------|---------|
| `results_dir` | string | Directory path, supports env expansion | user's PolyGraph-Results directory | Where report files are written. |
| `report_format` | string | `markdown`, `json`, `both` | `markdown` | Output format for the generated report. |
| `artifacts_tmp` | string | Directory path | `/tmp/polygraph_tmp` | Scratch directory for test-generated temporary files. |
| `config_file` | string | File path, supports env expansion | relative `./config/polygraph.yaml` | Path to this config file (circular reference for self-documentation). |

---

## 8. `reports` — Report Generation Options

```yaml
reports:
  include_spec_version: true     # Embed spec version in report header
  include_raw_responses: false   # Full LLM responses in report?
  response_preview_chars: 80    # Truncate previews to N chars
  exit_code_on_failure: true    # Non-zero exit on any test failure?
  overall_grade_method: "strict" # strict / majority / weighted
```

| Field | Type | Constraints | Default | Purpose |
|-------|------|-------------|---------|---------|
| `include_spec_version` | boolean | true/false | true | Embed spec version string in report header for provenance tracking. |
| `include_raw_responses` | boolean | true/false | false | Include full model responses (useful for post-hoc review, increases file size significantly). |
| `response_preview_chars` | integer | min 20, max 500 | 80 | Number of characters from the beginning of each response shown as a preview in reports. |
| `exit_code_on_failure` | boolean | true/false | true | CLI returns exit code 1 if any test scores 0; exit code 0 if all pass or are borderline. Enable for CI pipelines. |
| `overall_grade_method` | string | `strict`, `majority`, `weighted` | `strict` | **strict**: ALL categories must meet thresholds (critical_path always enforced). **majority**: >50% of tests at threshold or above. **weighted**: critical-path categories count double in the percentage calculation. |

---

## 9. Environment Variable Expansion

All string fields support `${ENV_VAR:-default_value}` expansion. Expansion happens at load time using `os.environ.get()`. Nested expansion is NOT supported (only one level). If the named env var does not exist and no default is provided, expansion silently yields an empty string.

Examples:
- `${POLYGRAPH_API_KEY}:${NO_VAR:-fallback}` → reads POLYGRAPH_API_KEY from env, "fallback" for NO_VAR
- `http://${HOST:-127.0.0.1}:11434/v1` → expands HOST or defaults to localhost

---

## 10. Backward Compatibility Policy

- New top-level keys may be added without bumping the spec MAJOR version, as long as they have sensible defaults and do not change test behavior.
- Removing or renaming an existing key bumps the spec MAJOR version.
- Provider chain entries are additive; adding a new entry to the end of the chain is backward-compatible.
- Profile test lists may grow (MINOR) but an identifier being removed from ALL profiles requires a MAJOR bump — existing runner scripts reference IDs by string match.
