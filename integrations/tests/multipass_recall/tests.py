"""Multi-pass recall benchmark — plugin tests module.

Wraps the existing benchmark_multipass.py methodology into TestDefinitions so
the Polygraph runner can include multi-pass recall quality verification as an
optional, conditionally-loaded test category.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class TestDefinition:
    """One multi-pass recall test case."""

    test_id: str = ""
    category: str = "MemoryRecall"
    prompt_template: str = ""
    expected_criteria: Dict[str, Any] = field(default_factory=dict)
    scoring_function: str = ""
    result_shape: str = "multipass_result"


def discover_tests(config: Dict[str, Any]) -> List[TestDefinition]:
    """Build the multi-pass recall test definitions.

    Args:
        config: params dict from polygraph_test_plugins.yaml.

    Returns:
        A flat list of TestDefinitions for this plugin.
    """
    num_passes = config.get("num_passes", 3)
    min_improvement_pct = config.get("min_improvement_pct", 50)

    tests: List[TestDefinition] = []

    # One definition per pass, so runner can score delta across runs
    for pass_num in range(1, num_passes + 1):
        tests.append(TestDefinition(
            test_id=f"MP_{pass_num:03d}",
            category="MultiPassRecall",
            prompt_template=(
                "Run recall pass {pass_num} against the same seed facts and"
                " record search latency, top-N key names, and precision score."
            ).format(pass_num=pass_num),
            expected_criteria={
                "min_passes": num_passes,
                "min_improvement_pct": min_improvement_pct,
                "passes_this_run": pass_num,
            },
            scoring_function="tests.multipass_recall.scorer.score_multipass",
            result_shape="multipass_result",
        ))

    # One aggregate delta test at the end
    tests.append(TestDefinition(
        test_id="MP_DELTA",
        category="MultiPassRecall",
        prompt_template=(
            "Compare pass 1 vs. final pass: recall should improve by"
            " at least {min_improvement_pct} percentage points."
        ).format(min_improvement_pct=min_improvement_pct),
        expected_criteria={
            "min_improvement_pct": min_improvement_pct,
        },
        scoring_function="tests.multipass_recall.scorer.score_delta",
        result_shape="delta_report",
    ))

    return tests
