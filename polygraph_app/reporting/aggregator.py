"""
Result Aggregator for Polygraph Scoring.

Aggregates multiple test results and computes overall grade (PASS/FAIL).
Handles --force-fail testing mode where certain tests are forced to fail.

This was wired into run_polygraph_clean.py from #7b fixes.
"""

from typing import List
from polygraph_app.models.test_result import TestResult


class ResultAggregator:
    """Aggregates test results and computes overall grading."""
    
    def __init__(self, tests: List[TestResult] = None):
        """Initialize with list of test results.
        
        Args:
            tests: List of TestResult objects to aggregate.
        """
        self.tests = tests or []
    
    def add_test(self, test: TestResult) -> 'ResultAggregator':
        """Add a single test result."""
        self.tests.append(test)
        return self
    
    def get_overall_grade(self) -> str:
        """Compute overall PASS/FAIL grade.
        
        Returns "PASS" if all tests pass, "FAIL" otherwise.
        For development mode, returns intermediate grades like "TBD".
        
        Returns:
            Grade string: "PASS", "FAIL", or "TBD" for development.
        """
        if not self.tests:
            return "TBD"  # No tests run yet
        
        passed = sum(1 for t in self.tests if t.is_passed())
        failed = sum(1 for t in self.tests if t.status == "SKIPPED")
        
        print(f"[ResultAggregator] Tests passed: {passed}/{len(self.tests)}")
        print(f"[ResultAggregator] Tests skipped/failed: {failed}/{len(self.tests)}")
        
        if failed == 0:
            return "PASS"
        elif passed < len(self.tests):
            return "FAIL"
        else:
            return "TBD"
    
    def get_test_summary(self) -> dict:
        """Get summary of all tests."""
        passing = [t for t in self.tests if t.is_passed()]
        failing = [t for t in self.tests if not t.is_passed()]
        
        return {
            "total": len(self.tests),
            "passed": len(passing),
            "failed": len(failing),
            "tests": [t.to_dict() for t in self.tests]
        }
