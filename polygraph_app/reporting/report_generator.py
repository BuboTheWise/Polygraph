"""
Report Generator for Polygraph Scoring.

Generates formatted output (JSON or text) from aggregated test results.
Supports CI integration with --output flag for format selection.

This was part of the scoring integration from #7b fixes.
"""

from typing import Union
import json


class ReportGenerator:
    """Generates reports in JSON or text format."""
    
    def __init__(self, tests, output_format: str = "json"):
        """Initialize report generator.
        
        Args:
            tests: List of test results (TestResult objects or dicts)
            output_format: "json" or "text" for the output format
        """
        self.tests = tests if isinstance(tests, list) else []
        self.output_format = output_format.lower()
    
    def generate_json(self) -> str:
        """Generate JSON report."""
        
        # Aggregate test results  
        total_passed = sum(1 for t in self.tests if hasattr(t, 'is_passed') and t.is_passed())
        total_tests = len(self.tests)
        
        report_data = {
            "status": "PASS" if total_passed == total_tests else "FAIL",
            "total_tests": total_tests,
            "passed": total_passed,
            "failed": total_tests - total_passed,
            "tests": [t.to_dict() if hasattr(t, 'to_dict') else t for t in self.tests]
        }
        
        return json.dumps(report_data, indent=2)
    
    def generate_text(self) -> str:
        """Generate human-readable text report."""
        lines = [
            "=" * 60,
            "POLYGRAH TEST REPORT",
            "=" * 60,
            f"Format: {self.output_format.upper()}",
            "-" * 40,
        ]
        
        total_passed = sum(1 for t in self.tests if hasattr(t, 'is_passed') and t.is_passed())
        total_tests = len(self.tests)
        overall_status = "PASS" if total_passed == total_tests else "FAIL"
        
        lines.extend([
            f"Overall Status: {overall_status}",
            f"Total Tests: {total_tests}",
            f"Passed: {total_passed}",
            f"Failed: {total_tests - total_passed}",
            "",
            "Test Results:",
            "-" * 40,
        ])
        
        for test in self.tests:
            status_symbol = "✓ PASS" if hasattr(test, 'is_passed') and test.is_passed() else "✗ FAIL/SKIPPED"
            lines.append(f"  [{test.test_id}] {status_symbol} - {test.test_name}")
        
        lines.extend(["", "=" * 60])
        
        return "\n".join(lines)
    
    def to_dict(self) -> dict:
        """Get report as dictionary."""
        total_passed = sum(1 for t in self.tests if hasattr(t, 'is_passed') and t.is_passed())
        total_tests = len(self.tests)
        
        return {
            "status": "PASS" if total_passed == total_tests else "FAIL",
            "total_tests": total_tests,
            "passed": total_passed,
            "failed": total_tests - total_passed,
            "tests": [t.to_dict() if hasattr(t, 'to_dict') else t for t in self.tests]
        }
