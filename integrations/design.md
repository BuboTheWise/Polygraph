# Integration Plugin Architecture for Optional Tests

## Problem Statement

The core Polygraph verification battery has 11 hardcoded test categories covering model-verification capabilities (truthfulness, safety, reasoning, etc.). System-level verification tests -- memory benchmarks, multi-pass recall, custom domain-specific checks -- need to load conditionally via configuration without polluting the core. The runner must stay generic: adding a new integration plugin should never require modifying `run_polygraph.py`.

This design defines the complete plugin interface, loader contract, configuration schema, directory structure, and runner extension points so third-party test suites can participate alongside the built-in battery with zero changes to core code.

## Design Goals

1. **Core stays generic** -- `scripts/run_polygraph.py` only knows about its own 11 model-verification categories. It delegates "plugin tests" to `PluginLoader`, which returns a flat category map the runner consumes identically.
2. **Configuration-driven registration** -- A YAML config declares which integration plugins are active, with per-plugin parameters and enable/disable toggles.
3. **Standard interface** -- Every plugin exposes the same lightweight protocol: `discover_tests(config)`, plus optional hooks (`setup`, `teardown`, `score_test`). The protocol is versioned via `spec_version` in the manifest.
4. **Lazy, fault-tolerant loading** -- Plugins are imported on demand. Missing dependencies silently degrade: a plugin that fails to load is skipped with a warning, never blocking core tests.
5. **Spec-version alignment** -- Each manifest declares `spec_version`. The loader warns if a plugin targets an older interface version and provides backward-compatibility shims for known transitions.
6. **Namespace isolation** -- Each test plugin lives under `integrations/tests/<name>/` with its own `plugin.yaml` manifest + `tests.py` module, preventing import collisions between plugins.

## Architecture Overview

```
+-------------------+     config      +------------------+
|  run_polygraph.py | <-------------  | PluginLoader     |
|  (runner)         |   category_map  | (integrations/   |
|                   | --------------> |  tests/__init__) |
|  - SEVERITY_TESTS |                 +--------+---------+
|  - test dispatch  |                          |
|  - scoring, report                      loads enabled plugins
+-------------------+                  from config/polygraph_test_plugins.yaml
                                        |
                    +-------------------+-------------------+
                    |                   |                   |
              +-----v------+   +-------v------+   +--------v-------+
              | memory_benchmark | multipass_recall | <custom plugin>|
              | ---------------- | --------------- | --------------|  |
              | plugin.yaml   |  | plugin.yaml  |   | plugin.yaml    |
              | tests.py      |  | tests.py     |   | tests.py       |
              +--------------+  +-------------+   +----------------+
```

## Directory Layout

```
Polygraph/
├── config/
│   ├── polygraph.yaml                     # Core battery config (profiles, categories, provider)
│   └── polygraph_test_plugins.yaml        # Plugin registry: which plugins to enable/configure
├── scripts/
│   ├── run_polygraph.py                   # Standalone runner (consumes plugin category map)
│   └── polygraph_config.py                # Runtime config loader + validation
├── tests/
│   ├── __init__.py
│   └── test_plugin_loader.py              # Plugin Loader test suite
├── integrations/
│   ├── __init__.py                        # Framework-wide init (empty or import hooks)
│   ├── design.md                          # This file
│   └── tests/                             # Integration test plugins namespace
│       ├── __init__.py                    # PluginLoader + TestDefinition dataclass plugin interface
│       ├── memory_benchmark/              # Example: memory search recall benchmarks
│       │   ├── plugin.yaml                # Manifest
│       │   └── tests.py                   # discover_tests(...) implementation
│       └── multipass_recall/              # Example: multi-pass memory quality
│           ├── plugin.yaml
│           └── tests.py
├── references/scripts/                    # Detailed test specs (prompts, rubrics)
└── docs/                                  # Schema reference, change log
```

## Plugin Interface Protocol

### Required: `discover_tests(config: Dict[str, Any]) -> List[TestDefinition]`

**The only mandatory entry point.** The loader calls this with the parameters section from config after flattening (see below). It must return a list of TestDefinition-like objects. The result may be a dict keyed by category; the loader flattens it via `.items()` values.

```python
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class TestDefinition:
    """A single test case provided by an integration plugin."""

    id_: str                                # unique within the plugin (e.g., "MB_001")
    category: str                           # human-readable grouping label
    prompt_template: str                    # can include {placeholder} for params
    expected_criteria: Dict[str, Any]       # pass/fail thresholds and scoring params
    scoring_function: str                   # dotted function path OR "inline"
    result_shape: str = "model_response"    # shape the scorer expects


def discover_tests(config: Dict[str, Any]) -> List[TestDefinition]:
    """Return list of test definitions this plugin provides."""
    ...
```

### Optional lifecycle hooks

These exist for advanced plugins that need state management. The loader tolerates their absence without warning.

#### `setup() -> bool`

Called once before any test in the plugin runs. Returns ``True`` on success, ``False`` to abort this entire plugin. A failed setup drops ALL tests from this plugin, logs the reason, and continues with other plugins.

```python
def setup() -> bool:
    """One-time initialization (e.g., connect to external service). Return False to disable plugin."""
    global _memory_client
    try:
        _memory_client = MemorySearchClient(...)
        return True
    except ConnectionError:
        logging.warning("Cannot reach %s — disabling memory_benchmark plugin" % endpoint)
        return False
```

#### `teardown()`

Called once after all tests in the plugin complete (even if some failed). Used to release resources. If it raises, the exception is logged but does NOT affect test scores already collected.

```python
def teardown():
    """Cleanup resources after all tests complete."""
    global _memory_client
    if _memory_client:
        _memory_client.close()
```

#### `score_test(test_id: str, raw_response: Any) -> float`

Per-test scoring override. If absent, the runner falls back to the generic 0-3 rubric using `expected_criteria` from the test definition as a guideline. The plugin can return any value in [0.0, 3.0].

```python
def score_test(test_id: str, raw_response: Any) -> float:
    """Score a single test result (optional override)."""
    ...
```

### Spec Versioning

The manifest must declare `spec_version` -- the interface version the plugin was written against:

| spec_version | Notes                                   |
| -------------- |----------------------------------------- |
| `1.0`          | Initial: `discover_tests(params)`, `TestDefinition` dataclass with 6 fields. Optional `setup`/`teardown`/`score_test`. |

The loader warns if a plugin's spec version is older than the current interface. It does not block loading -- backward compat shims handle known transitions (e.g., the v1.0 -> v2.0 rename of `id_` field). If a newer version arrives, plugins with mismatched spec versions log a warning but still attempt to load.

## Plugin Manifest (`plugin.yaml`)

Each plugin ships with a manifest at `<name>/plugin.yaml`:

```yaml
---                                 # YAML document marker recommended
name: memory_benchmark              # Short identifier (matches directory name)
version: 1.0.0                      # Semantic version of the plugin code itself
spec_version: "1.0"                # Interface version this plugin targets
description: >-
  Memory search recall/latency benchmarks so optional test
  categories can participate in the Polygraph runner without
  hardcoding them into the core battery.
categories:                         # Free-form tags for searching/organizing
  - MemoryRecall
  - Benchmarks
author: Polygraph Project          # Attribution (optional)
license: MIT                       # License (optional)
```

**Validation rules enforced by loader:**
- `name` must match the directory name.
- `version` must be a valid semver string (major.minor.patch).
- `spec_version` must be present and match a known schema version; unknown versions log a warning but still load.
- `description` is free-form, recommended to describe WHAT the plugin verifies.
- Missing fields beyond `name` + `version` get sensible defaults (`spec_version: "0"`, empty categories list).

### Dependency declaration (optional fields)

Starting with spec version 1.1, plugins declare their dependencies in the manifest:

```yaml
dependencies:
  python_packages:
    - name: pymupdf
      required: false           # If missing, plugin is skipped gracefully
    - name: httpx
      required: true            # Hard requirement -- skip import attempt to save time
  binaries:                     # OS-level prerequisites
    - curl
```

When `required: true` is absent or false, the loader attempts the import but skips on failure. When `required: true`, a missing dependency logs a clear error explaining what to install.

## Plugin Registry Configuration (`config/polygraph_test_plugins.yaml`)

Users enable/disable plugins via this file without modifying any code:

```yaml
plugins:
  memory_benchmark:
    enabled: true
    params:
      data_dir: "~/.local/share/polygraph/benchmarks"
      fact_count: 10

  multipass_recall:
    enabled: false             # Opt-in, may require specific environment setup
    params:
      num_passes: 3
      min_improvement_pct: 50
```

**Config shape normalization:** The loader accepts three equivalent config forms (tolerance for user convenience):

1. **Bool shortcut:** `memory_benchmark: true` -- enabled with empty params.
2. **Dict form:** `memory_benchmark: {enabled: true, params: {...}}` -- full control.
3. **Flat or nested params:** `params` key is optional; any fields other than `enabled`, `categories`, and `params` are treated as direct parameters forwarded to `discover_tests()`. The nested `params` key gets flattened into the same dict.

### Parameter resolution

Parameters flow through this chain:
1. Manifest in `plugin.yaml` provides defaults (if authors choose to encode them).
2. `polygraph_test_plugins.yaml` overrides manifest values.
3. CLI ``--plugin-params`` flag merges on top as final override.

The flattened params dict is passed directly to ``discover_tests(params)``. Plugins read what they need and ignore the rest.

See Config-driven registration in goals above.

## Plugin Loader (`integrations/tests/__init__.py`)

The `PluginLoader` class:

1. **Reads** `config/polygraph_test_plugins.yaml` (or ``--test-plugins-config`` path).
2. **For each enabled plugin**, loads `plugin.yaml` manifest, validates fields.
3. **Imports** `<name>/tests.py` via `importlib.util.spec_from_file_location` -- no site-packages dependency.
4. **Calls** optional `setup()` hook; skips the plugin if setup returns False.
5. **Calls** ``discover_tests(params)`` to obtain TestDefinition objects.
6. **Returns** a flat dict mapping ``plugin:<name>/<category>`` -> [TestDefinition] via `get_category_map()`.

The runner receives this category map and treats plugin categories identically to its built-in ones -- same dispatch, scoring, reporting.

### Key behaviors enforced
All of these are tested (see test_plugin_loader.py):
- **Enabled plugins load:** Two plugins with 2+3 tests each -> loader returns 5 total.
- **Disabled skip:** `enabled: false` in config means the plugin does NOT appear in `get_plugins()`.
- **No manifest = skipped:** Missing or invalid `plugin.yaml` results in a warning and a missing category for that plugin name, which drops from every query method.
- **Import failures isolated:** A plugin with import errors does not block or abort loading of other plugins. It is silently dropped -- it does not appear in any query result so downstream worker code never sees partial state.
- **discover_tests() failures isolated:** Same rule applies to errors raised during ``discover_tests`` execution (e.g., if the function crashes on certain parameters). The problematic plugin disappears from `get_plugins()` and `get_category_map()`. The loader continues processing remaining plugins unaffected.
- **Category key flattening:** Plugin tests with multiple internal categories get grouped under ``plugin:<name>/<category>`` keys to avoid collisions with built-in category names. A ``MemoryRecall`` test from memory_benchmark does not collide with a hypothetical ``MemoryRecall`` built-in category because the ``plugin:`` namespace qualifier keeps them distinct.
- **Flat/nested parameter forwarding:** Whether users write `params:` or flat keys, discover_tests receives a flattened dict. The loader strips `enabled` and `categories` from the forwarded params (they are metadata, not test parameters) so plugins never see configuration noise.

## Runner Integration Point

The runner gains ONE new capability: ability to merge plugin tests into its category index. This is additive -- core test dispatching remains untouched.

```python
# In run_polygraph.py (approximate integration point)
from integrations.tests import PluginLoader

def get_all_tests(config_path, severity_profile):
    builtins = load_builtin_tests(severity_profile)   # existing 11 categories
    plugin_loader = PluginLoader(
        base_dir=Path(__file__).resolve().parent.parent / "integrations" / "tests"
    )
    plugin_loader.load(config_path=config_path)
    plugin_cats = plugin_loader.get_category_map()   # category -> [TestDefinition]

    # Merge -- plugin categories live under "plugin:" prefix, no collision risk
    all_tests = {**builtins, **plugin_cats}
    return all_tests
```

### CLI hooks

| Flag | Purpose | Default                          |
|------|---------|----------------------------------|
| ``--test-plugins-config`` | Path to plugin registry YAML | ``config/polygraph_test_plugins.yaml`` |
| ``--plugin-params``       | Override params (JSON string) | ``{}`` (use config file values)   |

### Unified report format

Plugin tests appear in output with the `plugin:` category prefix. The runner scores them using the same 0-3 rubric as built-in categories. Plugin-specific scoring takes precedence if the plugin defines `score_test()`. In the JSON report, each test result carries its original category key so consumers can filter by ``plugin:*`` if desired.

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Plugin manifest is YAML, separate from code | Clean metadata/code boundary; manifests are human-readable and version-control friendly |
| `discover_tests(config)` returns TestDefinition objects | Self-describing test payloads; runner doesn't need to know plugin internals |
| Config-driven enable/disable | Users opt into heavy benchmark suites without touching code |
| Lazy import + graceful degradation | Missing optional deps (e.g., memory search services) don't block core tests |
| Plugins under `integrations/tests/` | Single namespace for all extension points; keeps the repo flat |
| Category key prefixing (`plugin:<name>/`) | Eliminates name collisions between plugins and built-in categories |
| No plugin cross-references by default | Each plugin is self-contained. Future work may add dependency ordering (Phase 3).

## Security Boundaries

- **No shell execution:** Plugins run as Python modules via `importlib`. They cannot execute arbitrary shell commands unless they explicitly call `subprocess` inside their own code -- something the loader does not grant.
- **Isolated sys.modules keys:** Each plugin imports under a unique name (`integration_plugin_<name>`) to prevent module caching issues between plugins of the same name in different directories.
- **No network access required:** Plugins are lazy-loaded only when enabled. A user who disables all plugins has zero import side effects from the extensions directory.

## Phased Implementation Plan

### Phase 1: Core plugin interface + loader (DONE -- t_9b0381a9)
**Status:** Complete with 7 passing tests covering all core load paths.

- [x] `TestDefinition` dataclass and `PluginInfo` in ``integrations/tests/__init__.py`` (240 lines).
- [x] `PluginLoader.load()` reads YAML, validates manifests, imports modules.
- [x] Fault tolerance: import errors and discover failures don't block other plugins.
- [x] Config normalization: bool shortcut, flat/nested params supported.
- [x] Category map flattening with ``plugin:<name>/<cat>`` keys.
- [x] Example plugins: ``memory_benchmark``, ``multipass_recall``.

### Phase 2: Runner integration + unified output (CHILD TASK)
**Assignee:** cthugha or default (implementation specialist).

- [ ] Wire ``PluginLoader`` into ``run_polygraph.py`` so plugin tests appear in dispatch alongside built-ins.
- [ ] Add ``--test-plugins-config`` CLI argument to runner.
- [ ] Plugin tests scored with same rubric + JSON report format.
- [ ] Optional ``score_test()`` hook honored if present.

### Phase 3: Lifecycle hooks and dependency management (FUTURE)
**Assignee:** default (architecture oversight).

- [ ] `setup()` / `teardown()` lifecycle hooks in loader with proper error isolation.
- [ ] Manifest-based dependency declarations (`python_packages`, `binaries`) with graceful skip logic.
- [ ] Spec version enforcement warnings + backward-compat shims table.

### Phase 4: Distribution-ready packaging (FUTURE)

**Assignee:** default (release management).

- [ ] Pack plugins as installable extras (e.g., ``pip install polygraph[memory_benchmark]``).
- [ ] Plugin discovery via entry points in addition to config-driven loading.
- [ ] Third-party plugin registry documentation.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Plugins introduce hard dependencies that break the runner | Runner fails to start entirely | Lazy imports + graceful skip; plugins only load when explicitly enabled in config. Core runner starts fine with all plugins disabled. |
| Plugin scoring functions expect different data shapes | Scores become meaningless across plugins | ``TestDefinition.result_shape`` declares the expected input format. The runner wraps raw responses before passing them to scorer overrides. |
| Config schema version diverges between core and plugin manifests | Silent behavior changes, broken params | ``spec_version`` in manifest + loader warning on mismatch. Known transitions have compatibility shims. Future major interface bumps will increment spec_major only for breaking changes. |
| Multiple plugins define the same test ID | Results get overwritten or duplicated | Test IDs are scoped to plugin namespace (``plugin:<name>/MB_001`` in output). Unique constraint enforced at plugin level, not global. |
| Plugins run long and block runner timeout | CI timeouts or user frustration | Per-category ``timeout_per_test`` applies equally to plugin categories. The flag inherits the severity profile timeout. A future per-plugin timeout override would go here.
