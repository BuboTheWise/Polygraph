"""Memory benchmark tests — discover_tests() implementation.

Exports TestDefinition objects so the PluginLoader can include memory search
recall and latency benchmarks alongside built-in Polygraph categories.

To see a full walkthrough, load the ``memory-benchmark-plugin`` skill or read:
<repo>/docs/design/integration-test-plugins.md
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class TestDefinition:
    """A single memory-benchmark test case (mirrors the loader schema)."""

    test_id: str = ""
    category: str = "MemoryRecall"
    prompt_template: str = ""               # can use {placeholder} for config values
    expected_criteria: Dict[str, Any] = field(default_factory=dict)
    scoring_function: str = ""              # dotted path OR "inline"
    result_shape: str = "model_response"   # shape the scorer expects


# ------------------------------------------------------------------
# Known facts to seed during benchmark runs (same as benchmark_memchorus.py)
# ------------------------------------------------------------------

FACTS = [
    {"key": "project_python_version",     "value": "Python 3.12 minimum required"},
    {"key": "deployment_target",           "value": "Kubernetes cluster in us-east-1"},
    {"key": "auth_mechanism",             "value": "OAuth2 with client credentials flow"},
    {"key": "database_sharding",          "value": "Shard by user_id hash modulo 64"},
    {"key": "cache_ttl_default",          "value": "300 seconds for API responses"},
    {"key": "monitoring_stack",           "value": "Prometheus + Grafana dashboards"},
    {"key": "ci_runner",                 "value": "GitHub Actions ubuntu-latest"},
    {"key": "code_review_policy",        "value": "Two approvals required for master merges"},
]


def _build_tests(data_dir: str, fact_limit: int) -> List[TestDefinition]:
    """Construct the concrete test definitions from config parameters."""
    tests: List[TestDefinition] = []

    for idx, fact in enumerate(FACTS[:fact_limit], start=1):
        tests.append(TestDefinition(
            test_id=f"MB_{idx:03d}",
            category="MemoryRecall",
            prompt_template=(
                "Search memory for '{key}' and return the stored value."
            ).format(key=fact["key"]),
            expected_criteria={
                "expected_key": fact["key"],
                "expected_value": fact["value"],
                "min_latency_ms": 50,       # hard stop if source is too slow
                "recall_rate_threshold": 0.5,
            },
            scoring_function="memchorus.tests.benchmark_memchrou.scor.score_memory",
            result_shape="search_result",
        ))

    return tests


def discover_tests(config: Dict[str, Any]) -> List[TestDefinition]:
    """Plugin entry point — called by PluginLoader during load.

    Args:
        config: params dict from polygraph_test_plugins.yaml (e.g. data_dir).

    Returns:
        A flat list of TestDefinitions for this plugin.
    """
    data_dir = str(
        Path(config.get("data_dir", "~/.hermes/memchorus_benchmarks")).expanduser()
    )
    fact_limit = config.get("fact_count", len(FACTS))

    return _build_tests(data_dir, fact_limit)
