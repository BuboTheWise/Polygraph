# pylint: disable=too-many-branches,too-many-locals
"""Integration test plugin interface for Polygraph conditional loading.

Plugins live under ``integrations/tests/<name>/`` with a ``plugin.yaml`` manifest
and ``tests.py`` module.  The ``PluginLoader`` discovers, validates, and loads
enabled plugins from a user-facing config file.  Missing dependencies gracefully
degrade — plugins that cannot load are skipped with warnings only.

Example usage (from run_polygraph.py)::

    from pathlib import Path
    from integrations.tests import PluginLoader

    MEMCHORUS_ROOT = Path(__file__).resolve().parent.parent
    loader = PluginLoader(
        base_dir=MEMCHORUS_ROOT / "integrations" / "tests"
    )
    loader.load(config_path=options.test_plugins_config)
    plugin_tests = loader.get_category_map()   # category -> [TestDefinition]

For a full walkthrough see the design doc at:
``docs/design/integration-test-plugins.md`` (committed alongside this code).
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Optional

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:
    yaml = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Data structures                                                             #
# --------------------------------------------------------------------------- #


@dataclass
class TestDefinition:
    """A single test case provided by an integration plugin."""

    id_: str                           # unique within the plugin (e.g. MB_001)
    category: str                      # human-readable grouping label
    prompt_template: str               # can include {placeholder} for params
    expected_criteria: Dict[str, Any]  # pass/fail thresholds & scoring params
    scoring_function: str              # dotted function path OR "inline"
    result_shape: str = "model_response"


@dataclass
class PluginInfo:
    """Loaded plugin metadata."""

    name: str
    version: str
    description: str          # from manifest
    categories: List[str]     # free-form tags


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _read_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """Read a YAML file safely. Returns ``None`` on any failure."""
    if yaml is None:
        logger.warning("PyYAML not installed — cannot read %s", path.name)
        return None
    try:
        with open(path) as fh:
            data = yaml.safe_load(fh)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("Failed to read %s: %s", path, exc)
        return None


# --------------------------------------------------------------------------- #
# Plugin loader                                                               #
# --------------------------------------------------------------------------- #


class PluginLoader:
    """Discovers and loads enabled integration-test plugins.

    Intended pattern::

        loader = PluginLoader(base_dir=MEMCHORUS_ROOT / "integrations" / "tests")
        loader.load(config_path=config_file)
        plugin_tests = loader.get_category_map()   # category -> tests

    The expected ``.yaml`` structure is::

        plugins:
          memory_benchmark:
            enabled: true
            params:
              fact_count: 8

    If a plugin can import but its ``discover_tests()`` raises, the plugin is
    silently dropped — it does *not* appear in ``get_plugins()`` or
    ``get_category_map()``.
    """

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir.resolve()
        self._plugins: Dict[str, PluginInfo] = {}
        self._tests: Dict[str, List[TestDefinition]] = {}
        # raw user config (kept for diagnostics)
        self._config: Dict[str, Any] = {}

    # -- public API -----------------------------------------------

    def load(self, config_path: Optional[Path] = None) -> None:  # noqa: C901
        """Parse the YAML registry file and load every enabled plugin."""
        if config_path is None:
            candidate = self.base_dir.parent.parent / "config" / "polygraph_test_plugins.yaml"
            if candidate.exists():
                config_path = candidate
            else:
                logger.info("No test-plugins config at %s — plugins will be silent.", candidate)
                return

        raw = _read_yaml(config_path)
        if not raw or "plugins" not in raw:
            logger.warning(
                "%s has no 'plugins' key — nothing to load.", config_path
            )
            return

        self._config = raw["plugins"]

        for name, cfg in self._config.items():
            self._load_one(name, cfg)

    # -- internal -------------------------------------------------

    def _load_one(self, name: str, cfg: Any) -> None:  # noqa: N802, C901
        """Import and register a single plugin (best-effort)."""
        # ── normalise config shape ────────────────────────
        if isinstance(cfg, bool):                       # myplugin: true
            enabled = cfg
            params: Dict[str, Any] = {}
        elif isinstance(cfg, dict):                     # myplugin: {enabled, …}
            enabled = cfg.get("enabled", True)
            params = {k: v for k, v in cfg.items() if k not in ("enabled", "categories")}
            # Flatten nested ``params`` key so discover_tests gets flat keys.
            if "params" in params and isinstance(params["params"], dict):
                params.update(params.pop("params"))
        else:
            logger.warning("Plugin '%s' has unrecognised config type (%r) — skipping.", name, type(cfg))
            return

        if not enabled:
            logger.info("Plugin '%s' is disabled — skipping.", name)
            return

        # ── manifest ─────────────────────────────────────
        plugin_dir = self.base_dir / name
        if not plugin_dir.is_dir():
            logger.warning("Plugin directory does not exist: %s", plugin_dir)
            return

        manifest_path = plugin_dir / "plugin.yaml"
        meta = _read_yaml(manifest_path)
        if meta is None:
            logger.warning("No valid %s — skipping plugin '%s'.", manifest_path, name)
            return

        # ── import + discover (metadata set LAST so failures leave no trace) ─
        mod: Optional[ModuleType] = None
        try:
            py_file = plugin_dir / "tests.py"
            mod_name = f"integration_plugin_{name}"
            spec = importlib.util.spec_from_file_location(mod_name, str(py_file))
            if not spec or not spec.loader:
                logger.error("Cannot get loader spec for %s — skipping.", py_file)
                return
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
        except Exception as exc:
            logger.warning("Failed to import plugin '%s': %s", name, exc)
            self._plugins.pop(name, None)
            return

        discovered: List[TestDefinition] = []
        if hasattr(mod, "discover_tests"):
            try:
                result = mod.discover_tests(params)
                if isinstance(result, dict):
                    for _k, items in result.items():
                        discovered.extend(items)
                else:
                    discovered = list(result)
            except Exception as exc:
                logger.warning("discover_tests() failed for '%s': %s — dropping plugin.", name, exc)
                self._plugins.pop(name, None)
                return

        # Only register *after* everything succeeds.
        self._plugins[name] = PluginInfo(
            name=name,
            version=meta.get("version", "0"),
            description=meta.get("description", ""),
            categories=meta.get("categories", []),
        )
        self._tests[name] = discovered
        logger.info("Loaded plugin '%s': %d tests registered.", name, len(discovered))

    # -- query API ------------------------------------------------

    def get_plugins(self) -> Dict[str, PluginInfo]:
        """Return loaded plugin metadata."""
        return dict(self._plugins)

    def get_tests(self) -> Dict[str, List[TestDefinition]]:
        """Return ``{plugin_name: [TestDefinition]}`` for every enabled plugin."""
        return {n: list(t) for n, t in self._tests.items()}

    def get_category_map(self) -> Dict[str, List[TestDefinition]]:
        """Flatten tests grouped by category under ``plugin:<name>/<cat>`` keys."""
        result: Dict[str, List[TestDefinition]] = {}
        for pname, tests in self._tests.items():
            by_cat: Dict[str, List[TestDefinition]] = {}
            for td in tests:
                by_cat.setdefault(td.category, []).append(td)
            for cat, items in by_cat.items():
                result[f"plugin:{pname}/{cat}"] = items
        return result
