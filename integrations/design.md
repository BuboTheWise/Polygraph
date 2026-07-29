# Integration Plugin Architecture for Optional Tests

## Problem Statement

The core Polygraph verification battery currently has test categories hardcoded. System-level verification tests (e.g., memory benchmarks, multi-pass recall) would need to be loaded conditionally via configuration without polluting the core. The runner should remain generic enough that adding a new test category or integration never requires modifying `run_polygraph.py`.

## Design Goals

1. **Core stays generic** — `scripts/run_polygraph.py` only knows about its own model-verification tests. It delegates "plugin tests" to whatever plugins are enabled in config.
2. **Configuration-driven registration** — A YAML config file declares which integration plugins are active, with per-plugin parameters.
3. **Standard interface** — All integration plugins implement the same lightweight protocol: `discover_tests()`, `run_test()`, `score_response()`.
4. **Lazy loading** — Plugins are not imported until their category is scheduled for execution. Missing dependencies silently degrade.
5. **Namespace isolation** — Each plugin lives under `integrations/plugins/<name>/` with its own `plugin.yaml` manifest + implementation module, mirroring the existing Hermes plugin convention.

## Architecture

### Directory Layout

```
MemChorus/
├── integrations/
│   ├── __init__.py             # (existing) runtime integration hooks
│   ├── hermes/                 # (existing) lifecycle hooks plugin
│   └── tests/                  # NEW: verification test plugins
│       ├── __init__.py         # PluginLoader class + IntegrationPlugin base protocol
│       ├── memory_benchmark/
│       │   ├── plugin.yaml     # name, version, description, categories[]
│       │   └── tests.py        # Test definitions implementing the protocol
│       ├── multipass_recall/
│       │   ├── plugin.yaml
│       │   └── tests.py
│       └── custom_verification/
│           ├── plugin.yaml
│           └── tests.py
├── config/
│   └── polygraph_test_plugins.yaml  # NEW: user-facing config for enabling/disabling plugins
└── scripts/
    └── run_polygraph.py        # MODIFIED: delegates plugin test discovery to PluginLoader
```

### Plugin Interface Protocol

Every integration test plugin provides a module-level function:

```python
def get_plugin_info() -> dict:
    """Return metadata about this plugin."""
    return {
        "name": "memory_benchmark",
        "version": "1.0.0",
        "categories": ["MemorySearch", "Benchmarks"],      # freeform tags
        "description": "Memory recall/latency benchmarks"
    }

def discover_tests(config: dict) -> List[TestDefinition]:
    """Return list of test definitions this plugin provides."""
    ...

class TestDefinition:
    """A single test case from an integration plugin."""
    test_id: str                # e.g. "MB_001"
    category: str               # human-readable label
    prompt_template: str        # can include {placeholder} for config values
    expected_criteria: dict     # pass/fail thresholds
    scoring_function: callable  # or path to scoring function string
```

### Configuration File (`config/polygraph_test_plugins.yaml`)

```yaml
plugins:
  memory_benchmark:
    enabled: true
    categories: ["MemorySearch"]
    params:
      data_dir: "~/.local/share/polygraph/benchmarks"
      fact_count: 10
  multipass_recall:
    enabled: false             # opt-in, requires specific environment
    params:
      num_passes: 3
  custom_verification:
    enabled: true
    categories: ["DataIntegrity"]
```

### Plugin Loader (`integrations/tests/__init__.py`)

The `PluginLoader` class:

1. Reads `config/polygraph_test_plugins.yaml` (or user-specified `--test-plugins-config`).
2. For each enabled plugin, loads `integrations/tests/<name>/plugin.yaml` for metadata, then imports `<name>/tests.py`.
3. Calls `discover_tests(config_params)` to get the list of test definitions.
4. Returns a flat dict mapping `category -> [TestDefinition, ...]` that the runner consumes identically to built-in tests.

### Runner Integration (`scripts/run_polygraph.py`)

The runner gains two new capabilities:
- A `--test-plugins-config` CLI argument (defaults to `config/polygraph_test_plugins.yaml`).
- A plugin category in `SEVERITY_TESTS` — when the severity profile selects a plugin category, the loader provides the actual tests.

The core test definitions remain unchanged. Plugin tests appear alongside built-in categories in results output. A plugin that cannot load (dependency missing) is logged and skipped gracefully.

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Plugin YAML manifest separate from code | Mirrors `integrations/hermes/plugin.yaml` convention already in the repo |
| `discover_tests(config)` returns TestDefinition objects | Each plugin declares its own tests; runner doesn't need to know test internals |
| Config-driven enable/disable | User opts into heavy benchmark suites without modifying code |
| Lazy import on demand | Missing dependencies (e.g., MemPalace MCP) don't block core tests |
| Plugins under `integrations/tests/` | Keeps the integrations directory as a single namespace for all extension points |

## Phased Approach

**Phase 1** (this task): Design + implementation of the plugin interface, loader, config schema, and example plugin wrapping the existing memory benchmark.

**Phase 2** (child task): Refactor `run_polygraph.py` to consume plugin tests alongside built-in categories, with unified output formatting.

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Plugins introduce hard dependencies | Lazy imports + graceful skip with warning log |
| Plugin scoring functions need different data shape | `TestDefinition` carries a `result_shape` field; runner wraps the raw response before passing to scorer |
| Config schema changes break plugins | `get_plugin_info()` includes a spec_version matching the interface version |
