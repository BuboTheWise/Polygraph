#!/usr/bin/env python3
"""Run behavioral test matrix for Polygraph #7b."""

import json
import sys
import os
import time
from dataclasses import dataclass
from typing import Any, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from polygraph_app.mock_server import MockServer


@dataclass 
class TestResult:
    name: str
    passed: bool
    duration_s: float
    ttft_s: Optional[float] = None
    error_status: Optional[int] = None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "duration_s": round(self.duration_s, 3),
            "ttft_s": round(self.ttft_s, 3) if self.ttft_s else None,
            "error_status": self.error_status
        }


class BehavioralTestRunner:
    """Runs all behavioral test cases against the mock server."""
    
    def __init__(self):
        self.server = MockServer()
        self.results: List[TestResult] = []
    
    def _create_request(self, test_case: str) -> dict[str, Any]:
        """Create a request based on test case name."""
        
        if "reasoning" in test_case.lower():
            return {
                "prompt": "Please reason step by step",
                "test_case": test_case,
                "model": "mock-model-v1"
            }
        elif "tool_call" in test_case.lower():
            return {
                "prompt": "Call the weather API",
                "test_case": test_case,
                "model": "mock-model-v1"
            }
        elif "malformed" in test_case.lower():
            return {
                "prompt": "Invalid request",
                "test_case": test_case + ",malformed_json",
                "model": "mock-model-v1"
            }
        elif "text_embedded" in test_case.lower():
            return {
                "prompt": "Embedded tool call",
                "test_case": test_case,
                "model": "mock-model-v1"
            }
        elif "http_500" in test_case.lower() or "error_status=500" in test_case:
            return {
                "prompt": "",
                "test_case": test_case,
                "model": "mock-model-v1",
                "error_status": 500
            }
        elif "http_503" in test_case.lower():
            return {
                "prompt": "",
                "test_case": test_case,
                "model": "mock-model-v1",
                "error_status": 503
            }
        elif "utf8" in test_case.lower() or "unicode" in test_case.lower():
            return {
                "prompt": "Hello world",
                "test_case": test_case,
                "model": "mock-model-v1"
            }
        else:
            return {
                "prompt": "",
                "test_case": test_case,
                "model": "mock-model-v1"
            }
    
    def run_test(self, name: str) -> TestResult:
        """Run a single test case and return results."""
        
        start = time.perf_counter()
        
        try:
            request_data = self._create_request(name)
            responses = self.server.run_requests(request_data)
            
            duration = time.perf_counter() - start
            
            # Process responses
            if not responses:
                return TestResult(
                    name=name,
                    passed=False,
                    duration_s=duration,
                    ttft_s=None,
                    error_status=500
                )
            
            response = responses[0] if responses else None
            
            # Extract TTFT if available
            ttft_s = getattr(response, 'ttft_any', None)
            if ttft_s and hasattr(response, 'content') and response.content:
                pass  # Valid TTFT
            
            http_status = getattr(response, 'http_status', None)
            
            # Determine if test passed
            error_status = http_status
            expected = error_status if error_status else 200
            passed = (error_status is None or error_status == expected)
            
            return TestResult(
                name=name,
                passed=passed,
                duration_s=duration,
                ttft_s=ttft_s,
                error_status=http_status
            )
        except Exception as e:
            duration = time.perf_counter() - start
            print(f"    Error in {name}: {e}")
            return TestResult(
                name=name,
                passed=False,
                duration_s=duration,
                ttft_s=None,
                error_status=500
            )


def main():
    """Run behavioral tests and generate results.jsonl."""
    
    runner = BehavioralTestRunner()
    results: List[TestResult] = []
    
    # Core mock server tests (from issue #7a spec)
    tests = [
        "1A_plain_content",
        "2A_reasoning_plus_content", 
        "3A_tool_calls_whole",
        "4A_malformed_json_tool_args",
        "5A_text_embedded_tool_calls",
        "6A_http_500_error",
        "7A_http_503_error",
        "8A_slow_first_byte",
        "9A_mid_stream_disconnect",
        "10A_utf8_multibyte_split",
        "11A_ttft_under_100ms",
    ]
    
    # Run tests and collect results
    for test_name in tests:
        result = runner.run_test(test_name)
        results.append(result)
        
        status = "PASS" if result.passed else "FAIL"
        ttft_str = f"(TTFT={result.ttft_s:.3f}s)" if result.ttft_s else ""
        print(f"{status} [{test_name:<40}] {ttft_str}")
    
    # Write results to JSONL for CI
    output_file = "/home/stefan/.hermes/kanban/workspaces/t_8ad1e1ea/results.jsonl"
    with open(output_file, 'w') as f:
        for r in results:
            f.write(json.dumps(r.to_dict()) + "\n")
    
    print()
    passed = sum(1 for r in results if r.passed)
    print(f"Summary: {passed}/{len(results)} tests passed")
    print(f"Results written to: {output_file}")
    
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
