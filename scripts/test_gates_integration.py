#!/usr/bin/env python3
"""
Integration test demonstrating correctness gates with INVALID marking.

This script simulates a concurrency run where:
- Level 1 (baseline): clean execution with sufficient samples → VALID
- Level 4: injects error to demonstrate gate failure → INVALID — gates failed

Expected output shows the difference between valid and invalid levels.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from polygraph_app.concurrency import RequestMetrics, LevelMetrics


def simulate_concurrency_run():
    """Simulate a concurrency harness run with correct gates applied."""
    
    print("=" * 70)
    print("CORRECTNESS GATES INTEGRATION TEST")
    print("Simulating concurrent levels with INVALID marking demonstration")
    print("=" * 70)
    
    # Import gates module
    from polygraph_app.gates import (
        apply_hard_fails,
        compare_to_baseline,
        generate_gate_report,
    )
    
    # Level 1: Baseline - clean execution with 25 samples
    print("\n--- Level 1 (baseline) ---")
    baseline_samples = []
    for i in range(25):
        baseline_samples.append(RequestMetrics(
            request_id=f"L1-r{i:03d}",
            t_start=0.1 + i * 0.01,
            t_first_token=0.5 + i * 0.02,
            t_done=2.0 + i * 0.03,
            e2e=1.9 + i * 0.04,
        ))
    
    # Check hard fails for baseline
    valid, failures = apply_hard_fails(baseline_samples, level=1)
    print(f"Hard fail check: {'PASS' if valid else 'FAIL'}")
    if not valid:
        for f in failures:
            print(f"  - {f}")
    
    n_samples = len(baseline_samples)
    ttft_n = n_samples  # Simplified for demo
    e2e_n = n_samples
    
    if valid and ttft_n >= 20 and e2e_n >= 20:
        status = "VALID — gates passed"
    else:
        status = "INVALID — gates failed"
    
    print(f"Samples: {n_samples} (threshold: >= 20)")
    print(f"P95 metrics available: {ttft_n >= 20 and e2e_n >= 20}")
    print(f"STATUS: {status}")
    
    # Level 4: Inject error to demonstrate gate failure
    print("\n--- Level 4 (with injected error) ---")
    level4_samples = []
    
    # First 20 samples clean
    for i in range(20):
        level4_samples.append(RequestMetrics(
            request_id=i,
            t_start=0.1 + i * 0.01,
            t_first_token=0.55 + i * 0.02,
            t_done=2.2 + i * 0.03,
            e2e=2.1 + i * 0.04,
        ))
    
    # Inject one error sample to trigger hard fail
    for i in range(5):
        level4_samples.append(RequestMetrics(
            request_id=i + 20,
            t_start=0.1 + (i + 20) * 0.01,
            error_class="TimeoutError",  # Inject timeout error
            error_message="Request timed out at level 4 under load",
            t_done=30.0,  # Simulate timeout
        ))
    
    # Check hard fails for level 4
    valid, failures = apply_hard_fails(level4_samples, level=4)
    print(f"Hard fail check: {'PASS' if valid else 'FAIL'}")
    if not valid:
        for f in failures:
            print(f"  - {f}")
    
    n_samples = len(level4_samples)
    ttft_n = sum(1 for s in level4_samples if hasattr(s, 't_first_token'))
    e2e_n = sum(1 for s in level4_samples if hasattr(s, 'e2e'))
    
    print(f"Total samples: {n_samples}")
    print(f"Valid TTFT samples: {ttft_n} (threshold: >= 20)")
    print(f"Valid E2E samples: {e2e_n} (threshold: >= 20)")
    
    # Also compute drop vs baseline
    if baseline_samples and level4_samples:
        comparison = compare_to_baseline(level4_samples, baseline_samples, margin_drop=10.0)
        print(f"\nBaseline pass rate: {comparison['baseline_pass_rate']:.2%}")
        print(f"Level 4 pass rate: {comparison['current_pass_rate']:.2%}")
        print(f"Drop points: {comparison.get('drop_points', 'N/A'):.2f}")
        
        if not comparison.get('gates_passed', True):
            print(f"GATE REASON: {comparison.get('failure_reason', 'Dropped below margin')}")
    
    # Determine status
    has_errors = any(s.error_class and s.error_class != "none" for s in level4_samples)
    if not valid or ttft_n < 20 or e2e_n < 20 or has_errors:
        print(f"STATUS: INVALID — gates failed")
    else:
        print(f"STATUS: VALID — gates passed")
    
    return 0


def main():
    """Run integration test and return exit code."""
    import sys
    
    try:
        result = simulate_concurrency_run()
        return result if result is not None else 0
    except Exception as e:
        print(f"\n[polygraph #5b] Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return 3


if __name__ == "__main__":
    sys.exit(main())
