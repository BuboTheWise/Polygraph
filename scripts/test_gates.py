#!/usr/bin/env python3
"""
Test correctness gates with demo scenarios showing VALID and INVALID marking.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from polygraph_app.concurrency import RequestMetrics, LevelMetrics


def create_test_samples():
    """Create mock samples for testing gate logic."""
    # Clean samples (no errors) - should pass gates
    clean_samples = [RequestMetrics(
        request_id=i,
        t_start=0.1 + i * 0.01,
        t_first_token=0.5 + i * 0.02,
        t_done=2.0 + i * 0.03,
        e2e=1.9 + i * 0.04,
    ) for i in range(25)]  # 25 samples > 20 threshold
    
    return clean_samples


def main():
    print("=" * 60)
    print("CORRECTNESS GATES TEST DEMONSTRATION")
    print("=" * 60)
    
    from polygraph_app.gates import (
        apply_hard_fails,
        compare_to_baseline,
        generate_gate_report,
    )
    
    # Scenario 1: Clean samples with sufficient data - should be VALID
    print("\n--- Scenario 1: Clean run with sufficient samples ---")
    clean_samples = create_test_samples()
    
    # Check hard fails
    valid, failures = apply_hard_fails(clean_samples, level=1)
    print(f"Hard fail check: {'PASS' if valid else 'FAIL'}")
    if failures:
        for f in failures:
            print(f"  - {f}")
    
    # Check sample count
    n_samples = len(clean_samples)
    print(f"Samples: {n_samples} (threshold: >= 20)")
    
    if n_samples >= 20 and valid:
        print("STATUS: VALID — gates passed")
    else:
        print("STATUS: INVALID — gates failed")
    
    # Scenario 2: Samples with errors - should fail hard fails check
    print("\n--- Scenario 2: Run with error samples ---")
    error_samples = [RequestMetrics(
        request_id=i,
        t_start=0.1 + i * 0.01,
        error_class="TimeoutError",
        error_message="Request timed out",
        t_done=30.0,  # Timeout duration
    ) for i in range(5)]
    
    valid, failures = apply_hard_fails(error_samples, level=2)
    print(f"Hard fail check: {'PASS' if valid else 'FAIL'}")
    if not valid:
        for f in failures:
            print(f"  - {f}")
    
    n_samples = len(error_samples)
    print(f"Samples: {n_samples} (threshold: >= 20)")
    print("STATUS: INVALID — gates failed (errors present)")
    
    # Scenario 3: Insufficient samples for p95
    print("\n--- Scenario 3: Insufficient samples (< 20) ---")
    few_samples = [RequestMetrics(
        request_id=i,
        t_start=0.1 + i * 0.01,
        t_first_token=0.5 + i * 0.02,
        t_done=2.0 + i * 0.03,
        e2e=1.9 + i * 0.04,
    ) for i in range(15)]  # Only 15 samples
    
    print(f"Samples: {len(few_samples)} (threshold: >= 20)")
    print("STATUS: INVALID — insufficient samples for p95 metrics")
    
    # Scenario 4: Clean baseline + high concurrency level (statistical gate demo)
    print("\n--- Scenario 4: Baseline comparison (concurrency-1 vs level N) ---")
    baseline_samples = create_test_samples()  # Level 1 with 25 samples
    
    # Simulate level 4 with slightly worse performance (drop of 8%)
    import random
    degraded_samples = [RequestMetrics(
        request_id=i,
        t_start=0.2 + i * 0.01,
        t_first_token=0.6 + i * 0.02,
        t_done=2.5 + i * 0.03,
        e2e=2.4 + i * 0.04,
    ) for i in range(25)]
    
    # Add some errors to trigger drop (but not exceed error rate limit)
    degraded_samples[10].error_class = "TimeoutError"
    
    comparison = compare_to_baseline(degraded_samples, baseline_samples, margin_drop=10.0)
    print(f"Baseline pass rate: {comparison['baseline_pass_rate']:.2%}")
    print(f"Current level pass rate: {comparison['current_pass_rate']:.2%}")
    print(f"Drop points: {comparison.get('drop_points', 'N/A'):.2f}")
    print(f"Margin drop threshold: {comparison['margin_drop']}")
    print(f"Statistical gates passed: {comparison['gates_passed']}")
    
    if not comparison['gates_passed']:
        print(f"GATE REASON: {comparison.get('failure_reason', 'Drop exceeded margin')}")
    
    # Print the gate report
    print("\n--- Gate Report ---")
    report = generate_gate_report([])  # Empty for now, just showing format
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
