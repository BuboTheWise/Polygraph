#!/usr/bin/env python3
"""
Demo Report Generator - Standalone demonstration of Polygraph reporting.

Shows example usage of ReportGenerator with mock scenarios for presentation/demo.

Usage:
    python demo_report_generator.py [--format json|text]
    
Output demonstrates the CI-ready JSON output format and human-readable text reports.
"""

import argparse
import json
import sys

sys.path.insert(0, "/home/stefan/.hermes/Projects/Polygraph")


def main():
    """Run demo with default scenario."""
    parser = argparse.ArgumentParser(description="Demo Report Generator for Polygraph")
    parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format")
    args = parser.parse_args()
    
    print("=" * 70)
    print("POLYGRAH DEMO REPORT GENERATOR")  
    print("=" * 70)
    print()
    print("This demo shows the report generation capabilities of Polygraph.")
    print("Use case: CI/CD pipelines, API responses, command-line reporting.")
    print()
    
    # Define a mock test suite for demonstration  
    demo_tests = [
        {
            "test_id": "1A",
            "test_name": "Authorization header handling", 
            "description": "Verify auth headers are passed correctly",
            "status": "COMPLETED",
            "passing_categories": ["tool_use_reliability"],
            "failing_categories": [],
            "ttft_ms_val": 12.5,
            "actual_tokens_used": 45
        },
        {
            "test_id": "2A",
            "test_name": "Tool payload tuple handling", 
            "description": "Handle tool call responses with tuples",
            "status": "COMPLETED",
            "passing_categories": ["tool_use_reliability"], 
            "failing_categories": [],
            "ttft_ms_val": 8.3,
            "actual_tokens_used": 120
        },
        {
            "test_id": "4A",
            "test_name": "Instruction following check",
            "description": "Verify model follows all instructions", 
            "status": "SKIPPED",  # Demo scenario: force-fail case
            "passing_categories": [],
            "failing_categories": ["instruction_following"], 
            "ttft_ms_val": None,
            "actual_tokens_used": None
        }
    ]
    
    print(f"[demo] Scenario: Mixed results (2 passed, 1 failed for --force-fail demo)")
    print(f"[demo] Output format: {args.format.upper()}")
    print()
    
    # Generate and display report
    from polygraph_app.reporting.report_generator import ReportGenerator
    
    generator = ReportGenerator(demo_tests, args.format)
    
    if args.format == "json":
        report = json.loads(generator.generate_json())
        print(json.dumps(report, indent=2))
    else:
        print(generator.generate_text())
    
    # Show exit code recommendation  
    status = "PASS" if all(t["status"] == "COMPLETED" for t in demo_tests) else "FAIL" 
    print()
    print(f"[demo] Recommended exit code: 0 (PASS) or 1 (FAIL) based on overall_grade")
    
    return report


if __name__ == "__main__":
    main()
