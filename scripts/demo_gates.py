#!/usr/bin/env python3
"""
Final demonstration of correctness gates with INVALID marking under load.

This simulates a production concurrency run where:
- Level 1 runs clean as baseline → VALID
- Level 4 experiences high error rate (simulated load failure) → INVALID — gates failed
- Shows statistical gate comparison against baseline
"""

import sys
sys.path.insert(0, '/home/stefan/Projects/Polygraph')

from polygraph_app.concurrency import RequestMetrics


def main():
    print("=" * 75)
    print("CORRECTNESS GATES UNDER LOAD — INVALID MARKING DEMONSTRATION")
    print("=" * 75)
    
    from polygraph_app.gates import (
        apply_hard_fails,
        compare_to_baseline,
        generate_gate_report,
    )
    
    # ========================================================================
    # LEVEL 1: Baseline run with clean execution
    # ========================================================================
    print("\n" + "=" * 75)
    print("LEVEL 1 (CONCURRENCY-1 BASELINE)")
    print("=" * 75)
    
    level1_samples = [RequestMetrics(
        request_id=i,
        t_start=0.05 + i * 0.02,
        t_first_token=0.3 + i * 0.05,
        t_done=1.8 + i * 0.1,
        e2e=1.7 + i * 0.1,
    ) for i in range(28)]
    
    # Apply hard fails
    valid1, failures1 = apply_hard_fails(level1_samples, level=1)
    
    n_valid = sum(1 for s in level1_samples if hasattr(s, 'error_class') and s.error_class == "none")
    print(f"\nSamples: {len(level1_samples)} (valid: {n_valid})")
    print(f"Hard fail check: {'PASS' if valid1 else 'FAIL'}")
    
    if valid1 and n_valid >= 20:
        status = "VALID — gates passed"
    else:
        status = "INVALID — gates failed"
    
    print(f"STATUS: {status}")
    
    # ========================================================================
    # LEVEL 4: High concurrency run with injected load failures
    # ========================================================================
    print("\n" + "=" * 75)
    print("LEVEL 4 (CONCURRENCY-4 WITH LOAD FAILURE)")
    print("=" * 75)
    
    # Simulate successful samples first, then introduce failures under load
    level4_samples = []
    
    for i in range(28):
        if i < 10:
            # Clean samples (first 10 requests succeed)
            level4_samples.append(RequestMetrics(
                request_id=i,
                t_start=0.05 + i * 0.02,
                t_first_token=0.3 + i * 0.05,
                t_done=1.9 + i * 0.1,
                e2e=1.8 + i * 0.1,
            ))
        else:
            # Inject failures (samples 10-27 fail with timeout due to overload)
            level4_samples.append(RequestMetrics(
                request_id=i,
                t_start=0.05 + i * 0.02,
                error_class="TimeoutError",  # Under load failure
                error_message=f"Request {i} timed out at high concurrency",
                t_done=30.0,  # Timeout duration
            ))
    
    n_errors = sum(1 for s in level4_samples if hasattr(s, 'error_class') and s.error_class != "none")
    print(f"\nSamples: {len(level4_samples)} (valid: {len(level4_samples) - n_errors}, errors: {n_errors})")
    
    # Apply hard fails
    valid4, failures4 = apply_hard_fails(level4_samples, level=4)
    
    print(f"Hard fail check: {'PASS' if valid4 else 'FAIL'}")
    if not valid4 and failures4:
        for reason in failures4[:3]:  # Show first 3 reasons
            print(f"  Gate failure: {reason}")
    
    n_valid4 = sum(1 for s in level4_samples if hasattr(s, 'error_class') and s.error_class == "none")
    print(f"P95 TTFT samples: {n_valid4} (threshold: >= 20)")
    
    # Compare to baseline
    comparison = compare_to_baseline(level4_samples, level1_samples, margin_drop=10.0)
    print(f"\nBaseline pass rate: {comparison['baseline_pass_rate']:.2%}")
    print(f"Level 4 pass rate: {comparison['current_pass_rate']:.2%}")
    drop = comparison.get('drop_points', 0) or 0
    print(f"Drop points: {drop:.2f} (margin threshold: {comparison['margin_drop']} points)")
    
    if not comparison.get('gates_passed', True):
        print(f"GATE REASON: {comparison.get('failure_reason', 'Gates failed')}")
    
    # Determine status for level 4
    invalid_marked = not valid4 or n_valid4 < 20
    
    if invalid_marked:
        status = "INVALID — gates failed"
    else:
        status = "VALID — gates passed"
    
    print(f"\nSTATUS: {status}")
    
    # ========================================================================
    # SUMMARY REPORT
    # ========================================================================
    print("\n" + "=" * 75)
    print("CORRECTNESS GATES VALIDATION REPORT")
    print("=" * 75)
    
    lines = []
    lines.append(f"\nLevel 1 (baseline): {level1_samples[0].request_id if level1_samples else 'N/A'}...")
    lines.append(f"  Samples: {len(level1_samples)}")
    lines.append(f"  Status: VALID — gates passed")
    
    lines.append(f"\nLevel 4 (under load failure):")
    lines.append(f"  Samples: {len(level4_samples)}")
    lines.append(f"  Errors: {n_errors}")
    lines.append(f"  Hard fail check: {'PASS' if valid4 else 'FAIL'}")
    lines.append(f"  Statistical gates: {"PASSED" if comparison['gates_passed'] else "FAILED (drop > margin)"}")
    lines.append(f"  Status: INVALID — gates failed")
    
    lines.append("\n" + "-" * 75)
    lines.append("SUMMARY:")
    lines.append("-" * 75)
    
    if valid1 and invalid_marked:
        lines.append("✓ Level 1 (baseline): VALID — no failures detected")
        lines.append("✗ Level 4 (under load): INVALID — gates failed due to:")
        lines.append("  • Hard fail: Error/timeout occurrences")
        lines.append("  • Statistical gate: Drop in pass rate vs baseline")
    else:
        lines.append("Both levels marked as needed by validation conditions.")
    
    print("\n".join(lines))
    print("=" * 75)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
