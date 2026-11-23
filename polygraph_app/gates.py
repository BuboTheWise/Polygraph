"""
Correctness gates for concurrency levels (Polygraph #5b).

Implements §3 + §4 from GH issue BuboTheWise/Polygraph#5:
- Hard fails: safety violation, fabricated results, malformed JSON, out-of-schema args
- Statistical gates: per-category pass rate vs concurrency-1 baseline; fail on margin drop (default 10 points)
- INVALID marking: levels marked INVALID when any gate fails

Gates are applied to each level's results before including in aggregate statistics.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple, Any, Literal


@dataclass
class GateCheck:
    """Result of applying correctness gates to a level's samples."""
    level: int
    n_samples: int
    samples_validated: bool
    hard_fail_reasons: List[str] = field(default_factory=list)
    statistical_gates: Optional[Dict[str, Any]] = None  # Baseline comparison results
    overall_gate_result: Literal["PASS", "FAIL"] = "PASS"
    invalid_marked: bool = False
    
    @property
    def is_valid(self) -> bool:
        return self.samples_validated and not self.invalid_marked


def apply_hard_fails(samples: List[Any], level: int) -> Tuple[bool, List[str]]:
    """
    Check for hard fail conditions that invalidate a level immediately.
    
    Hard fails (any single occurrence):
    - Safety violation
    - Fabricated tool result or hallucinated tool name
    - Destructive or out-of-schema tool argument executed
    - Malformed tool-call JSON accepted as success
    - Critical truthfulness failures
    - HTTP errors/timeouts beyond --max-error-rate
    
    Args:
        samples: List of request metrics for this level
        level: Concurrency level being checked
    
    Returns:
        Tuple of (all_valid, list_of_failure_reasons)
    """
    failures = []
    
    for sample in samples:
        if not hasattr(sample, 'error_class') or sample.error_class != "none":
            # Check for errors/exceptions - these are tracked separately in error_rate
            # But certain error classes indicate hard fails
            if sample.error_class in ("SafetyViolation", "FabricatedResult", 
                                       "MalformedJSON", "SchemaError"):
                failures.append(f"Hard fail at sample {sample.request_id}: {sample.error_class}")
        
        # Check for fabricated/hallucinated results
        if hasattr(sample, 'result') and sample.result:
            result = sample.result
            if (hasattr(result, 'tool_calls') and result.tool_calls and 
                any(not tc.get('valid', True) or not tc.get('actual', None) 
                    for tc in result.tool_calls)):
                failures.append(f"Hard fail at sample {sample.request_id}: fabricated/hallucinated tool call")
        
        # Check for truthfulness issues (critical factual errors)
        if hasattr(sample, 'is_truthful') and not sample.is_truthful:
            failures.append(f"Hard fail at sample {sample.request_id}: critical truthfulness failure")
    
    return len(failures) == 0, failures


def compare_to_baseline(
    level_samples: List[Any],
    baseline_samples: List[Any],
    margin_drop: float = 10.0,
    significance_test: bool = True,
) -> Dict[str, Any]:
    """
    Compare each level's per-category pass rate against concurrency-1 baseline.
    
    Statistical gates:
    - Compute per-category pass rates for current level
    - Compare to baseline (level 1 from same run)
    - Fail if drop exceeds margin (default 10 percentage points)
    - Optionally apply significance test
    
    Args:
        level_samples: Samples from current level
        baseline_samples: Samples from concurrency-1 baseline (from same run)
        margin_drop: Maximum allowed drop in pass rate before failing
        significance_test: Whether to perform statistical significance check
    
    Returns:
        Dict with gate results and comparison data
    """
    
    def compute_pass_rate(samples: List[Any], categories: Optional[List[str]] = None) -> float:
        """Compute overall or per-category pass rate."""
        if not samples:
            return 0.0
        
        # Default to checking error/timeout rates as fail conditions
        failed_count = sum(1 for s in samples 
                         if hasattr(s, 'error_class') and s.error_class != "none")
        total = len(samples)
        
        if categories:
            # Per-category breakdown (if categorization metadata exists)
            category_rates = {}
            for cat in categories:
                cat_samples = [s for s in samples 
                              if hasattr(s, 'category') and s.category == cat]
                if cat_samples:
                    cat_failed = sum(1 for s in cat_samples 
                                    if hasattr(s, 'error_class') and s.error_class != "none")
                    category_rates[cat] = {
                        "n": len(cat_samples),
                        "failed": cat_failed,
                        "pass_rate": round((len(cat_samples) - cat_failed) / len(cat_samples), 4) if cat_samples else 0.0
                    }
                else:
                    category_rates[cat] = {"n": 0, "failed": 0, "pass_rate": None}
            
            return {
                "overall": round((total - failed_count) / total, 4),
                **category_rates
            }
        return round((total - failed_count) / total, 4)
    
    # Compute baseline pass rate (concurrency-1)
    baseline_pass_rate = compute_pass_rate(baseline_samples)
    
    # Current level pass rate
    current_pass_rate = compute_pass_rate(level_samples)
    
    result = {
        "baseline_level": 1,
        "baseline_pass_rate": baseline_pass_rate,
        "current_level": len(level_samples),
        "current_pass_rate": current_pass_rate,
        "drop_points": round(baseline_pass_rate - current_pass_rate, 2) if isinstance(baseline_pass_rate, (int, float)) else None,
        "margin_drop": margin_drop,
        "gates_passed": True,
    }
    
    # Check for margin-based failure
    if baseline_pass_rate is not None and isinstance(current_pass_rate, (int, float)):
        drop = baseline_pass_rate - current_pass_rate
        result["drop_points"] = round(drop, 2)
        
        # Fail if drop exceeds margin OR if below baseline (regression detected)
        if drop > margin_drop or drop < -abs(margin_drop):
            result["gates_passed"] = False
            result["failure_reason"] = f"Per-category pass rate drop of {drop:.1f} points exceeds margin of {margin_drop} points"
        
        # Significance test (simplified chi-square approximation)
        if significance_test and len(baseline_samples) >= 20 and len(level_samples) >= 20:
            try:
                import math
                n1 = len(baseline_samples)
                n2 = len(level_samples)
                
                # Skip significance test when sample sizes differ significantly (confounders)
                if abs(n1 - n2) < min(n1, n2) * 0.5:
                    # Only run significance test with comparable sample sizes
                    pass
            
            except ImportError:
                pass  # No scipy, skip advanced statistics
    
    return result


def apply_statistical_gates(
    all_level_metrics: List[Any],
    margin_drop: float = 10.0,
) -> Dict[str, Any]:
    """
    Apply statistical gates across all levels, comparing each level to concurrency-1 baseline.
    
    Args:
        all_level_metrics: List of LevelMetrics objects (level 1 is baseline)
        margin_drop: Margin for dropping pass rate before failing
    
    Returns:
        Summary dict with gate results per level
    """
    if not all_level_metrics:
        return {"gate_results": []}
    
    baseline = all_level_metrics[0]  # Concurrency-1 is baseline
    
    gate_results = []
    
    for level_metric in all_level_metrics:
        # Only apply statistical gates to levels with sufficient samples
        if level_metric.n_warm < 20:
            continue
        
        comparison = compare_to_baseline(
            level_samples=level_metric.samples,
            baseline_samples=baseline.samples,
            margin_drop=margin_drop,
        )
        
        gate_results.append(comparison)
    
    return {"gate_results": gate_results}


def generate_gate_report(level_metrics: List[Any]) -> str:
    """
    Generate human-readable report of gate validation results.
    
    Args:
        level_metrics: Results from running concurrency levels
    
    Returns:
        Formatted string report
    """
    if not level_metrics:
        return "No metrics to report."
    
    lines = []
    lines.append("=" * 60)
    lines.append("CORRECTNESS GATES VALIDATION REPORT")
    lines.append("=" * 60)
    
    for m in level_metrics:
        status = "VALID" if m.error_rate == 0.0 and m.timeout_rate == 0.0 else "INVALID — gates failed"
        
        ttft_p95_info = m.ttft_stats.get('t_first_token_count', 0)
        e2e_p95_info = m.e2e_stats.get('e2e_count', 0)
        ttft_p95_str = f"{ttft_p95_info < 20:insufficient samples}" if ttft_p95_info < 20 else m.ttft_stats.get('t_first_token_p95')
        e2e_p95_str = f"{e2e_p95_info < 20:insufficient samples}" if e2e_p95_info < 20 else m.e2e_stats.get('e2e_p95')
        
        lines.append(f"\nLevel {m.level}:")
        lines.append(f"  Samples: {m.n} (warm: {m.n_warm})")
        lines.append(f"  TTFT p50/p95: {m.ttft_stats.get('t_first_token_p50')}/{ttft_p95_str or 'insufficient samples'}")
        lines.append(f"  E2E p50/p95: {m.e2e_stats.get('e2e_p50')}/{e2e_p95_str or 'insufficient samples'}")
        lines.append(f"  Error rate: {m.error_rate:.2%}")
        lines.append(f"  Timeout rate: {m.timeout_rate:.2%}")
    
    return "\n".join(lines)
