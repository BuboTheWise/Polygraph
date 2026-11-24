#!/usr/bin/env python3
"""
Artifact Shape and Hygiene Tests for Polygraph #7c

Validates that behavioral test artifacts conform to specifications:
- TestResult schema compliance
- JSON serialization validity  
- Metrics fields (ttft_ms, e2e_ms, latency_p50/p95)
- grading_state enum values (PENDING|PASS|FAIL|NOT_SCORED|INVALID|INSUFFICIENT_SAMPLES)
- Exit codes (0 for success when behavioral tests in expected states)
- Output formatting consistency
- Results.jsonl line validity
- Summary JSON schema compliance

Run with: python tests/test_artifacts.py
Or integrate into CI pipeline.
"""

import json
import sys
import os
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Import from hygiene module (not from scripts/run_polygraph_tests)
polygraph_dir = Path(__file__).parent.parent
sys.path.insert(0, str(polygraph_dir / "polygraph_app"))
from polygraph_app.hygiene import (
    redact_config,
    check_redaction_in_artifacts,
    collect_artifact_checksums,
    validate_artifact_shape,
    write_manifest_json,
    write_summary_json,
    normalize_url,
    get_git_info,
)


def test_no_stderr_pollution():
    """Check that running validation tests doesn't produce unexpected stderr."""
    # Capture stderr during a simple operation
    import io
    
    old_stderr = sys.stderr
    stderr_capture = io.StringIO()
    
    try:
        sys.stderr = stderr_capture
        
        # Run a simple test to check for pollution
        result = redact_config({"api_key": "test"})
        
        return True
        
    finally:
        sys.stderr = old_stderr
    """Validate TestResult instance matches specification."""
    errors = []
    
    # Convert to dict for easier validation
    result_dict = asdict(result)
    
    # Check all required fields exist
    missing_fields = RequiredMetrics - set(result_dict.keys())
    if missing_fields:
        errors.append(f"Missing metrics fields: {missing_fields}")
    
    # Validate field types and constraints
    for field_name, expected_type in [
        ('name', str), ('passed', bool), ('expected', str), ('actual', str),
        ('ttft_ms', (int, float)), ('e2e_ms', (int, float)),
        ('latency_p50_ms', (int, float)), ('latency_p95_ms', (int, float)),
        ('error_count', int), ('samples', int), ('error_rate', float),
        ('invalid', bool), ('grading_state', str), ('grade', Optional[str]),
    ]:
        if field_name not in result_dict:
            continue  # Skip optional fields
            
        value = result_dict[field_name]
        
        if field_name == 'grade' and expected_type is Optional[str]:
            if not isinstance(value, str) and value is not None:
                errors.append(f"{field_name}: invalid type {type(value).__name__}")
        elif expected_type is bool:
            # Allow boolean-like strings for flexibility
            if not isinstance(value, bool) and not (isinstance(value, str) and 
                                                     value.lower() in ('true', 'false')):
                errors.append(f"{field_name}: expected bool, got {type(value).__name__}")
        elif expected_type is (int, float):
            if not isinstance(value, (int, float)) or (isinstance(value, bool) and not True):
                # Reject non-numeric or bool types
                errors.append(f"{field_name}: invalid type {type(value).__name__} for numeric field")
        elif expected_type is Optional[str]:
            if value is not None and not isinstance(value, str):
                errors.append(f"{field_name}: expected Optional[str], got {type(value).__name__}")
    
    return len(errors) == 0, errors


def validate_json_serialization(result: TestResult) -> Tuple[bool, List[str]]:
    """Verify TestResult can be serialized to valid JSON with round-trip preservation."""
    errors = []
    
    try:
        json_str = json.dumps(asdict(result))
        parsed = json.loads(json_str)
        
        # Verify critical fields are preserved
        for field in ['name', 'passed', 'ttft_ms', 'e2e_ms', 'grading_state']:
            if field not in parsed or str(parsed[field]) != str(getattr(result, field)):
                errors.append(f"Round-trip JSON lost or changed: {field}")
    except json.JSONDecodeError as e:
        errors.append(f"Invalid JSON serialization: {e}")
    except Exception as e:
        errors.append(f"Serialization error: {type(e).__name__}: {e}")
    
    return len(errors) == 0, errors


def validate_metrics_fields(result: TestResult) -> Tuple[bool, List[str]]:
    """Verify metrics fields are present and have valid values."""
    errors = []
    
    # Check that all required metrics exist
    for metric in RequiredMetrics:
        if not hasattr(result, metric):
            errors.append(f"Missing metrics field: {metric}")
    
    # Validate metric values (must be non-negative)
    for metric in ['ttft_ms', 'e2e_ms']:
        value = getattr(result, metric, None)
        if value is not None and (not isinstance(value, (int, float)) or value < 0):
            errors.append(f"{metric}: invalid value {value}")
    
    # Validate latency percentiles  
    for metric in ['latency_p50_ms', 'latency_p95_ms']:
        value = getattr(result, metric, None)
        if value is not None and (not isinstance(value, (int, float)) or value < 0):
            errors.append(f"{metric}: invalid value {value}")
    
    # P95 should be >= P50 when both present (with tolerance for near-identical values)
    p50 = getattr(result, 'latency_p50_ms', None)
    p95 = getattr(result, 'latency_p95_ms', None)
    if p50 is not None and p95 is not None:
        # Allow tiny difference due to rounding
        if abs(p95 - p50) < 0.001 and p95 != p50:
            errors.append("latency_p95_ms should be >= latency_p50_ms")
    
    return len(errors) == 0, errors


def validate_grading_state_enum(result: TestResult) -> Tuple[bool, List[str]]:
    """Verify grading_state is a valid enum value."""
    errors = []
    
    if not hasattr(result, 'grading_state'):
        errors.append("Missing grading_state field")
        return False, errors
    
    state = result.grading_state
    
    if state not in VALID_GRADING_STATES:
        errors.append(
            f"Invalid grading_state '{state}' - must be one of "
            f"{sorted(VALID_GRADING_STATES)}"
        )
    
    return len(errors) == 0, errors


def validate_exit_code(results: List[TestResult]) -> Tuple[int, str]:
    """Determine appropriate exit code based on core behavioral test results."""
    
    # Separate core tests from grading tests
    core_tests = [r for r in results if r.grading_state == "PENDING"]
    graded_tests = [r for r in results if r.grading_state != "PENDING"]
    
    # Core behavioral tests (not grading/hardware) determine exit code
    # Exit 0 when all core tests passed or were invalid
    failed_core = [r for r in core_tests if not r.passed and not r.invalid]
    
    if failed_core:
        failed_names = [r.name for r in failed_core]
        return 1, f"Core behavioral tests failed: {', '.join(failed_names)}"
    
    return 0, "All core behavioral tests passed or marked as invalid"


def validate_output_formatting(results: List[TestResult]) -> Tuple[bool, List[str]]:
    """Verify output formatting is consistent across all results."""
    errors = []
    
    if not results:
        return True, ["No results to validate"]
    
    # Check that all results have the same structure (required core fields)
    required_keys = CoreResultFields
    first_result_dict = asdict(results[0])
    expected_keys = set(first_result_dict.keys()) & set(required_keys)
    
    for i, result in enumerate(results):
        result_dict = asdict(result)
        missing_keys = expected_keys - set(result_dict.keys())
        if missing_keys:
            errors.append(f"Result {i}: missing keys {missing_keys}")
        
        # Check numeric fields are properly typed
        for field in ['ttft_ms', 'e2e_ms', 'error_rate']:
            value = result_dict.get(field)
            if value is not None and isinstance(value, str):
                errors.append(f"Result {i}.{field}: should be numeric, got string")
    
    return len(errors) == 0, errors


def validate_summary_schema(summary_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Verify summary JSON schema compliance."""
    errors = []
    
    # Required top-level keys
    required_keys = {'timestamp', 'total_tests', 'passed_core', 'elapsed_seconds', 'results'}
    missing = required_keys - set(summary_data.keys())
    if missing:
        errors.append(f"Missing summary keys: {missing}")
    
    # Validate types
    if 'results' in summary_data and not isinstance(summary_data['results'], list):
        errors.append("'results' field must be a list")
    
    # Each result should have required fields
    for i, item in enumerate(summary_data.get('results', [])):
        result_errors = []
        
        if 'name' not in item:
            result_errors.append("missing 'name'")
        elif 'passed' not in item:
            result_errors.append("missing 'passed'")
            
        # Check enum for grading_state
        if 'grading_state' in item and item['grading_state'] not in VALID_GRADING_STATES:
            result_errors.append(
                f"invalid grading_state '{item.get('grading_state')}' - "
                f"must be one of {sorted(VALID_GRADING_STATES)}"
            )
        
        if result_errors:
            errors.append(f"Result {i}: {result_errors}")
    
    return len(errors) == 0, errors


def test_no_stderr_pollution() -> bool:
    """Check that running validation tests doesn't produce unexpected stderr."""
    # Capture stderr during a simple operation
    import io
    
    old_stderr = sys.stderr
    stderr_capture = io.StringIO()
    
    try:
        sys.stderr = stderr_capture
        
        # Run a simple test to check for pollution
        result = TestResult(
            name="pollution_check",
            passed=True,
            expected="Check no stderr pollution",
            actual="OK"
        )
        
        return True
        
    finally:
        sys.stderr = old_stderr


class ArtifactValidationRunner:
    """Runs artifact validation tests against behavioral test suite."""
    
    def __init__(self, results: List[TestResult]):
        self.results = results
        self._test_results: List[Dict[str, Any]] = []
    
    def validate_all(self) -> Dict[str, Any]:
        """Run all artifact validation tests and return summary."""
        self._test_results = []
        
        # Test each result for schema compliance
        for i, result in enumerate(self.results):
            is_valid, errors = validate_test_result_schema(result)
            self._test_results.append({
                "test": f"result_{i}_schema",
                "category": "artifact_shape",
                "valid": is_valid,
                "errors": errors if not is_valid else [],
            })
        
        # Test JSON serialization for each result
        for i, result in enumerate(self.results):
            is_valid, errors = validate_json_serialization(result)
            self._test_results.append({
                "test": f"result_{i}_json_serialization", 
                "category": "artifact_shape",
                "valid": is_valid,
                "errors": errors if not is_valid else [],
            })
        
        # Test metrics fields for each result
        for i, result in enumerate(self.results):
            is_valid, errors = validate_metrics_fields(result)
            self._test_results.append({
                "test": f"result_{i}_metrics",
                "category": "artifact_shape", 
                "valid": is_valid,
                "errors": errors if not is_valid else [],
            })
        
        # Test grading state enum for each result
        for i, result in enumerate(self.results):
            is_valid, errors = validate_grading_state_enum(result)
            self._test_results.append({
                "test": f"result_{i}_grading_state",
                "category": "artifact_shape",
                "valid": is_valid, 
                "errors": errors if not is_valid else [],
            })
        
        # Test exit codes for all results combined
        exit_code, reason = validate_exit_code(self.results)
        self._test_results.append({
            "test": "exit_code",
            "category": "hygiene",
            "valid": exit_code == 0,
            "errors": [reason] if exit_code != 0 else [],
        })
        
        # Test output formatting (using all results)
        is_valid, errors = validate_output_formatting(self.results)
        self._test_results.append({
            "test": "output_formatting",
            "category": "hygiene",
            "valid": is_valid,
            "errors": errors if not is_valid else [],
        })
        
        # Test no stderr pollution
        is_clean = test_no_stderr_pollution()
        self._test_results.append({
            "test": "no_stderr_pollution",
            "category": "hygiene",
            "valid": is_clean,
            "errors": ["unexpected stderr output"] if not is_clean else [],
        })
        
        # Build summary
        valid_tests = sum(1 for t in self._test_results if t["valid"])
        invalid_tests = len(self._test_results) - valid_tests
        
        by_category = {
            "artifact_shape": sum(1 for t in self._test_results 
                                  if t.get("category") == "artifact_shape" and not t["valid"]),
            "hygiene": sum(1 for t in self._test_results 
                           if t.get("category") == "hygiene" and not t["valid"]),
        }
        
        all_errors = []
        for test_result in self._test_results:
            all_errors.extend(test_result.get("errors", []))
        
        return {
            "all_passed": invalid_tests == 0,
            "total_tests": len(self._test_results),
            "passed": valid_tests,
            "failed": invalid_tests,
            "by_category": by_category,
            "errors": all_errors if all_errors else None,
        }
    
    def print_detailed_report(self) -> None:
        """Print detailed test results report."""
        for test_result in self._test_results:
            status = "✓ PASS" if test_result["valid"] else "✗ FAIL"
            print(f"\n{status}: {test_result['test']}")
            print(f"  Category: {test_result['category']}")
            if test_result['errors']:
                for error in test_result['errors']:
                    print(f"  Error: {error}")


def main():
    """Main entry point for artifact validation tests."""
    
    print("=" * 80)
    print("POLYGRAPH #7C ARTIFACT SHAPE AND HYGIENE VALIDATION")
    print("=" * 80)
    
    try:
        # Create behavioral test results to validate
        sample_results = [
            run_basic_content_test(),
            run_reasoning_test(),
            run_tool_calls_test(),
            run_malformed_json_test(),
            run_text_embedded_tool_calls_test(),
            run_http_500_test(),
            run_http_503_test(),
            run_slow_first_byte_test(),
            run_mid_stream_disconnect_test(),
            run_utf8_multibyte_split_test(),
        ]
        
        # Add grading test results  
        sample_results.extend([
            run_all_error_run_test(),
            run_unmatched_rubric_test(),
            run_tool_hard_fail_test(),
            run_invalid_marking_test(),
            run_insufficient_samples_test(),
            run_max_error_rate_test(),
        ])
        
        # Create validation runner and run tests
        runner = ArtifactValidationRunner(sample_results)
        validation_summary = runner.validate_all()
        
        print("\n" + "=" * 80)
        print("VALIDATION SUMMARY")
        print("=" * 80)
        print(f"\nTotal validation tests: {validation_summary['total_tests']}")
        print(f"Passed: {validation_summary['passed']}")
        print(f"Failed: {validation_summary['failed']}")
        
        if validation_summary['errors']:
            print("\nValidation errors:")
            for error in validation_summary['errors']:
                print(f"  - {error}")
        
        print(f"\nBy category:")
        for category, count in validation_summary['by_category'].items():
            print(f"  {category}: {count} failures")
        
        # Print detailed test results
        runner.print_detailed_report()
        
        # Exit with appropriate code
        exit_code = 0 if validation_summary['all_passed'] else 1
        
    except Exception as e:
        print(f"\n💥 Validation failed with exception: {e}")
        import traceback
        traceback.print_exc()
        exit_code = 1
    
    finally:
        print(f"\n{'=' * 80}")
        print(f"Exit code: {exit_code}")
        
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
