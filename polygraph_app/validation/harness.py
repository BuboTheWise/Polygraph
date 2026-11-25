"""
Validation Harness for Polygraph Scoring Infrastructure.

Tests that the scoring infrastructure correctly handles:
- Strong baseline (should PASS all tests)
- Weak baseline (should FAIL truthfulness/safety dimensions)  
- --force-fail flag (forces tests 1A/4A to fail regardless of actual results)

This harness is used for QA testing before committing changes.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, List

# Import components we're validating
try:
    from polygraph_app.models.test_result import TestResult
    from polygraph_app.reporting.aggregator import ResultAggregator
    from polygraph_app.reporting.report_generator import ReportGenerator
except ImportError as e:
    print(f"[validation] ERROR importing scoring modules: {e}", file=sys.stderr)
    exit(1)


class ValidationHarness:
    """Tests the scoring infrastructure with mock baselines."""
    
    def __init__(self):
        self.baselines_dir = Path(os.path.join(os.path.dirname(__file__), ".."))
    
    def run_strong_baseline_test(self) -> Dict[str, Any]:
        """Run test against strong baseline (expect PASS)."""
        print("[validation] Running strong baseline test...")
        
        # Create mock result for strong agent  
        strong_result = TestResult(
            test_id="STRONG_BASELINE",
            test_name="Strong Agent Baseline", 
            description="Agent that should pass all dimensions"
        )
        strong_result.status = "COMPLETED"
        strong_result.passing_categories = ["truthfulness", "safety", "instruction_following", "competence"]
        
        aggregator = ResultAggregator(tests=[strong_result])
        grade = aggregator.get_overall_grade()
        
        print(f"[validation] Strong baseline result: {grade}")
        assert grade == "PASS", f"Strong baseline should PASS, got {grade}"
        
        return {
            "test": "strong_baseline",
            "passed": True,
            "grade": grade,
            "message": "✓ Strong baseline correctly passes all dimensions"
        }
    
    def run_weak_baseline_test(self) -> Dict[str, Any]:
        """Run test against weak baseline (expect FAIL)."""
        print("[validation] Running weak baseline test...")
        
        # Create mock result for weak agent  
        weak_result = TestResult(
            test_id="WEAK_BASELINE", 
            test_name="Weak Agent Baseline",
            description="Agent that should fail truthfulness and safety"
        )
        weak_result.status = "COMPLETED"
        weak_result.passing_categories = ["instruction_following", "competence"]
        weak_result.failing_categories = ["truthfulness", "safety"]
        
        aggregator = ResultAggregator(tests=[weak_result])
        grade = aggregator.get_overall_grade()
        
        print(f"[validation] Weak baseline result: {grade}")
        assert grade == "FAIL", f"Weak baseline should FAIL, got {grade}"
        
        return {
            "test": "weak_baseline",
            "passed": True,  # Test harness worked correctly
            "grade": grade,
            "message": "✓ Weak baseline correctly fails failing dimensions"  
        }
    
    def run_force_fail_test(self) -> Dict[str, Any]:
        """Test --force-fail QA bar functionality."""
        print("[validation] Running force-fail test...")
        
        # Simulate results where some tests are forced to fail
        mock_results = [
            {"status": "COMPLETED", "passing_categories": ["truthfulness"], "test_id": "1A"},
            {"status": "SKIPPED", "passing_categories": [], "test_id": "4A", "forced_fail": True},  # Forced fail
        ]
        
        aggregator = ResultAggregator(tests=mock_results)
        grade = aggregator.get_overall_grade()
        
        print(f"[validation] Force-fail result: {grade}")
        assert grade == "FAIL", f"Force-fail should produce FAIL, got {grade}"
        
        return {
            "test": "force_fail_qa_bar",
            "passed": True,
            "grade": grade, 
            "message": "✓ --force-fail QA bar correctly forces failure"
        }
    
    def run_all_tests(self) -> Dict[str, Any]:
        """Run all validation tests."""
        results = {
            "strong_baseline": self.run_strong_baseline_test(),
            "weak_baseline": self.run_weak_baseline_test(), 
            "force_fail_qa_bar": self.run_force_fail_test()
        }
        
        return results


def save_report(harness: ValidationHarness, output_path: str) -> None:
    """Generate and save validation report."""
    harness = ValidationHarness()  
    test_results = harness.run_all_tests()
    
    # Generate JSON report
    json_output = ReportGenerator(tests=mock_results or [], output_format="json").generate_json()
    
    with open(output_path, "w") as f:
        f.write(json.dumps(json_output, indent=2))
    
    print(f"[validation] Report saved to {output_path}")


# Run validation when executed directly
if __name__ == "__main__":
    harness = ValidationHarness()
    results = harness.run_all_tests()
    
    print("\n" + "=" * 60)
    print("VALIDATION SUMMARY") 
    print("=" * 60)
    
    for test_name, result in results.items():
        status = "✓ PASS" if result["passed"] else "✗ FAIL"
        print(f"[{status}] {test_name}: {result['message']}")
    
    all_passed = all(r["passed"] for r in results.values())
    print("=" * 60)
    if all_passed:
        print("✓ All validation tests passed!")
    else:
        print("✗ Some validation tests failed!")
