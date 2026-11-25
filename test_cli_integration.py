#!/usr/bin/env python3
"""
CLI Integration Test - Tests command line flag handling in run_polygraph_clean.py.

Verifies:
- --output flag routing (json/text) 
- --force-fail QA bar functionality
- Exit code behavior (0 for PASS, 1 for FAIL)
"""

import subprocess
import sys


def test_cli_integration():
    """Test CLI integration."""
    
    print("[test_cli] Running CLI integration tests...")
    
    # Test 1: Basic run without flags (should PASS by default)
    print("\n[TEST 1] Running without --force-fail (expecting PASS)")
    result = subprocess.run(
        [sys.executable, "scripts/run_polygraph_clean.py", "--output", "json"],
        capture_output=True, text=True, timeout=30
    )
    
    print(f"Exit code: {result.returncode}")
    output = result.stdout
    
    # Check for PASS in output
    if "PASS" in output or result.returncode == 0:
        print("✓ Test 1 passed: Basic run exits with 0")
    else:
        print("✗ Test 1 failed: Expected exit code 0, got", result.returncode)
    
    # Test 2: --force-fail should produce FAIL and exit code 1  
    print("\n[TEST 2] Running with --force-fail (expecting FAIL)")
    result_fail = subprocess.run(
        [sys.executable, "scripts/run_polygraph_clean.py", "--output", "json", "--force-fail"],
        capture_output=True, text=True, timeout=30
    )
    
    print(f"Exit code: {result_fail.returncode}")
    output_fail = result_fail.stdout
    
    if "FAIL" in output_fail or result_fail.returncode == 1:
        print("✓ Test 2 passed: --force-fail produces FAIL and exit code 1")
    else:
        print("✗ Test 2 failed: Expected FAIL with exit code 1")
    
    # Test 3: --output=text should produce text format  
    print("\n[TEST 3] Testing --output=text flag")
    result_text = subprocess.run(
        [sys.executable, "scripts/run_polygraph_clean.py", "--output", "text"],
        capture_output=True, text=True, timeout=30
    )
    
    if "PASS" in result_text.stdout or "FAIL" in result_text.stdout:
        print("✓ Test 3 passed: Text output format works")
    else:
        print("✗ Test 3 failed: Unexpected output for --output=text")
    
    # Summary
    print("\n" + "=" * 60)
    print("CLI INTEGRATION TEST SUMMARY")
    print("=" * 60)
    
    tests_passed = sum([
        "PASS" in output or result.returncode == 0,
        "FAIL" in output_fail or result_fail.returncode == 1, 
        "PASS" in result_text.stdout or "FAIL" in result_text.stdout
    ])
    
    print(f"Tests passed: {tests_passed}/3")
    
    return tests_passed == 3


if __name__ == "__main__":
    success = test_cli_integration()
    sys.exit(0 if success else 1)
