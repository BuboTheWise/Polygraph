#!/usr/bin/env python3
"""Unit tests for the PluginLoader framework."""

from __future__ import annotations

import sys
from pathlib import Path

_workspace = Path(__file__).resolve().parent
sys.path.insert(0, str(_workspace))

from integrations.tests import PluginLoader


def _pk(tmp: Path, name: str, body: str):
    """Create a minimal plugin dir with manifest."""
    d = tmp / name; d.mkdir(exist_ok=True)
    (d / "plugin.yaml").write_text(
        f"name: {name}\nversion: 1.0\nspec_version: '1.0'\n"
        f"description: loader test\ncategories:\n  - TC\n"
    )
    (d / "tests.py").write_text(body)


# -- helpers for generating valid Python bodies ---------------------

_OK_TEMPLATE = """\
from integrations.tests import TestDefinition
def discover_tests(c):
  return [TestDefinition(id_='t'+str(i), category='GC', prompt_template='', expected_criteria={}, scoring_function='x') for i in range(N)]
"""


def _okbody(count):
    return _OK_TEMPLATE.replace("N", str(count))


_CAT_BODY = """\
from integrations.tests import TestDefinition
def discover_tests(c):
  return [TestDefinition(id_='u1', category='X', prompt_template='', expected_criteria={}, scoring_function='s'),
          TestDefinition(id_='v1', category='Y', prompt_template='', expected_criteria={}, scoring_function='s')]
"""


_PARAMS_BODY = """\
from integrations.tests import TestDefinition
def discover_tests(c):
  n = c.get('n', 1)
  return [TestDefinition(id_='t'+str(i), category='G', prompt_template='', expected_criteria={}, scoring_function='x') for i in range(n)]
"""

_ERR_BODY = "def discover_tests(c):\n  raise RuntimeError('oh')\n"


# -- actual tests ---------------------------------------------------

class TestLoaderOk:
    def test_two_plugins(self, tmp_path):
        r = tmp_path / "p"; r.mkdir(parents=True)
        _pk(r, "a", _okbody(2))
        _pk(r, "b", _okbody(3))
        (tmp_path / "c.yaml").write_text("plugins:\n  a: true\n  b: true\n")
        ld = PluginLoader(base_dir=r); ld.load(config_path=tmp_path / "c.yaml")
        assert len(ld.get_tests()["a"]) == 2
        assert len(ld.get_tests()["b"]) == 3

    def test_disabled_not_loaded(self, tmp_path):
        r = tmp_path / "p"; r.mkdir(parents=True)
        _pk(r, "x", _okbody(1))
        (tmp_path / "c.yaml").write_text("plugins:\n  x:\n    enabled: false\n")
        ld = PluginLoader(base_dir=r); ld.load(config_path=tmp_path / "c.yaml")
        assert "x" not in ld.get_plugins()

    def test_no_manifest_skipped(self, tmp_path):
        r = tmp_path / "p"; r.mkdir(parents=True)
        (r / "nm").mkdir(); (r / "nm" / "tests.py").write_text("")
        (tmp_path / "c.yaml").write_text("plugins:\n  nm: true\n")
        ld = PluginLoader(base_dir=r); ld.load(config_path=tmp_path / "c.yaml")
        assert "nm" not in ld.get_plugins()

    def test_import_err_dropped(self, tmp_path):
        r = tmp_path / "p"; r.mkdir(parents=True)
        _pk(r, "bad", "raise ImportError('nope')\n")
        (tmp_path / "c.yaml").write_text("plugins:\n  bad: true\n")
        ld = PluginLoader(base_dir=r); ld.load(config_path=tmp_path / "c.yaml")
        assert "bad" not in ld.get_plugins()

    def test_discover_err_dropped(self, tmp_path):
        r = tmp_path / "p"; r.mkdir(parents=True)
        _pk(r, "err", _ERR_BODY)
        (tmp_path / "c.yaml").write_text("plugins:\n  err: true\n")
        ld = PluginLoader(base_dir=r); ld.load(config_path=tmp_path / "c.yaml")
        assert "err" not in ld.get_plugins()

    def test_category_keys(self, tmp_path):
        r = tmp_path / "p"; r.mkdir(parents=True)
        _pk(r, "m", _CAT_BODY)
        (tmp_path / "c.yaml").write_text("plugins:\n  m: true\n")
        ld = PluginLoader(base_dir=r); ld.load(config_path=tmp_path / "c.yaml")
        cm = ld.get_category_map()
        assert any("m" in k for k in cm)

    def test_params_received(self, tmp_path):
        r = tmp_path / "p"; r.mkdir(parents=True)
        _pk(r, "pp", _PARAMS_BODY)
        (tmp_path / "c.yaml").write_text(
            "plugins:\n  pp:\n    enabled: true\n    params:\n      n: 5\n"
        )
        ld = PluginLoader(base_dir=r); ld.load(config_path=tmp_path / "c.yaml")
        assert len(ld.get_tests()["pp"]) == 5


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
