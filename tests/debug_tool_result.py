#!/usr/bin/env python3
"""Debug script to check what .result returns."""

import sys, json
sys.path.insert(0, "tests")
from tool_fixtures import invoke_fixture, MockToolCall

# Test 1: What does get_fixture_weather return?
print("=== Testing get_fixture_weather ===")
weather_result = invoke_fixture("get_fixture_weather", {"city": "Tokyo"})
print(f"Weather result: {weather_result}")
print(f"Type: {type(weather_result)}")
print(f"Keys: {list(weather_result.keys()) if isinstance(weather_result, dict) else 'N/A'}")

# Test 2: What does add return?
print("\n=== Testing add ===")
add_result = invoke_fixture("add", {"a": 12, "b": 8})
print(f"Add result: {add_result}")
print(f"Type: {type(add_result)}")

# Test 3: What does lookup_record return?
print("\n=== Testing lookup_record ===")
lookup_result = invoke_fixture("lookup_record", {"record_id": "user_1"})
print(f"Lookup result: {lookup_result}")
print(f"Type: {type(lookup_result)}")
print(f"Keys: {list(lookup_result.keys()) if isinstance(lookup_result, dict) else 'N/A'}")

# Test 4: Check MockToolCall.result property behavior
print("\n=== Testing MockToolCall.result ===")
tc = MockToolCall("get_fixture_weather", {"city": "Tokyo"})
print(f"Before execute - tc.function['execute_result']: {tc.function.get('execute_result')}")

# Access .result which should call .execute() internally
tc_result = tc.result
print(f"After accessing .result: {tc_result}")
print(f"Type: {type(tc_result)}")
print(f"Keys: {list(tc_result.keys()) if isinstance(tc_result, dict) else 'N/A'}")
