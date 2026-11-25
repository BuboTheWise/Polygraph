#!/usr/bin/env python3
"""
Test Report Generator - Standalone testing of report generation.

Tests the generate_json() and generate_text() methods from 
polygraph_app/reporting/report_generator.py in isolation.
"""

import sys
sys.path.insert(0, "/home/stefan/.hermes/Projects/Polygraph")

from polygraph_app.reporting.report_generator import ReportGenerator


def test_report_generator():
    """Test report generation functions."""
    
    # Create sample test results  
    tests = [
        {
            "test_id": "1A",
            "test_name": "Auth header passthrough", 
            "status": "COMPLETED",
            "passing_categories": ["tool_use_reliability"],
            "failing_categories": []
        },
        {
            "test_id": "4A", 
            "test_name": "Instruction following verification",
            "status": "SKIPPED",  # Forced fail for --force-fail testing
            "passing_categories": [],
            "failing_categories": ["instruction_following"]
        }
    ]
    
    print("[test_report_generator] Testing ReportGenerator...")
    
    # Test JSON generation  
    json_report = ReportGenerator(tests=tests, output_format="json").generate_json()
    print(f"\n[polygraph_clean] Generated JSON report:")
    print(json_report)
    
    # Test text generation
    text_report = ReportGenerator(tests=tests, output_format="text").generate_text()
    print(f"\n[polygraph_clean] Generated text report:")
    print(text_report)
    
    return {
        "json_generated": True, 
        "text_generated": True,
        "reports_validated": json_report and text_report
    }


if __name__ == "__main__":
    result = test_report_generator()
    sys.exit(0 if result["reports_validated"] else 1)
