#!/usr/bin/env python3
"""Memory benchmark integration plugin for Polygraph test framework.

Provides memory search recall/latency benchmarks as TestDefinitions that the
main runner can load conditionally via ``config/polygraph_test_plugins.yaml``.

To see a full walkthrough, load the ``memory-benchmark-plugin`` skill or read:
<repo>/docs/design/integration-test-plugins.md
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------
# TestDefinition lives in the loader module itself so plugins just export
# plain dicts (one per test) and get() materialises them into instances.
# --------------------------------------------------------------------------


@dataclass
class TestDefinition:  # noqa: F811 - intentional override for type hints
    """A single memory-benchmark test case."""

    id: str = ""
    description: str = ""
    expected_criteria: Dict[str, Any] = field(default_factory=dict)
    scoring_function: str = ""       # dotted path to callable OR "inline"
    result_shape: str = "model_response"  # shape the scorer expects