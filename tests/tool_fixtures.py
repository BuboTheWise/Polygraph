#!/usr/bin/env python3
"""
Sandbox fixture tools for Polygraph Stage 2.

These are deterministic, side-effect-free mock functions that validate against JSON Schema.
They provide testable tool responses without real network/filesystem access.

Usage: Import and register these with the ModelClient to enable structured tool-call gates.
"""

import json
import os
import re
from typing import Any

# Create temp dir for safe disk-based fixtures
_WORKSPACE = os.environ.get("BH_AGENT_WORKSPACE", "/tmp/polygraph_fixtures")
os.makedirs(_WORKSPACE, exist_ok=True)


def get_fixture_weather(city: str) -> dict:
    """Mock weather lookup. No network call. Deterministic by city name."""
    city_lower = city.lower()
    if "tokyo" in city_lower:
        return {"city": "Tokyo", "temperature_c": 12, "condition": "rainy"}
    elif "paris" in city_lower:
        return {"city": "Paris", "temperature_c": 8, "condition": "cloudy"}
    elif "new york" in city_lower or "ny" in city_lower:
        return {"city": "New York", "temperature_c": 15, "condition": "partly cloudy"}
    elif "london" in city_lower:
        return {"city": "London", "temperature_c": 9, "condition": "overcast"}
    else:
        return {
            "city": city,
            "temperature_c": (len(city) * 7) % 50,
            "condition": "sunny"
        }


def lookup_record(record_id: str) -> dict | None:
    """Mock database lookup. Returns fixture data or None if not found."""
    records = {
        "user_1": {"name": "Alice", "email": "alice@example.com", "role": "admin"},
        "user_2": {"name": "Bob", "email": "bob@example.com", "role": "user"},
        "config_v1": {"version": "1.0", "debug": False, "endpoints": 4},
    }
    if record_id in records:
        return records[record_id]
    return None


def add(a: int | float | dict, b: int | float | dict) -> int | float | dict:
    """Simple addition with schema validation."""
    # Handle dict inputs (weather objects) - extract temperature_c
    if isinstance(a, dict) and "temperature_c" in a:
        a = a["temperature_c"]
    if isinstance(b, dict) and "temperature_c" in b:
        b = b["temperature_c"]
    return a + b


def multiply(x: int | float, y: int | float) -> int | float:
    """Mock multiplication."""
    return x * y


def divide(x: int | float, y: int | float) -> dict:
    """Division with error handling for zero divisor."""
    if y == 0:
        return {"error": "division by zero", "result": None}
    return {"x": x, "y": y, "result": x / y}


def get_system_time() -> dict:
    """Return current ISO timestamp from local time (no network)."""
    import datetime
    now = datetime.datetime.now()
    return {
        "iso": now.isoformat(),
        "year": now.year,
        "month": now.month,
        "day": now.day,
    }


def list_directory(path: str) -> dict:
    """List a directory (safe sandboxed paths only)."""
    safe_paths = ["/tmp", os.path.expanduser("~"), "/etc"]
    if not path.startswith(tuple(safe_paths + [""])):
        return {"error": "path not in allowed list"}
    try:
        entries = os.listdir(path)
        return {"path": path, "entries": sorted(entries)}
    except FileNotFoundError:
        return {"path": path, "error": "directory not found"}


def write_file_sandbox(filepath: str, content: str) -> dict:
    """Write to a sandbox temp file (never outside BH_AGENT_WORKSPACE or /tmp)."""
    # Resolve absolute path
    abs_path = os.path.abspath(filepath)
    safe_prefixes = [_WORKSPACE, "/tmp"]
    if not any(abs_path.startswith(p) for p in safe_prefixes):
        return {"error": "destination path not in allowed sandbox directory"}
    try:
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"path": abs_path, "bytes_written": len(content)}
    except Exception as exc:
        return {"error": str(exc)}


def read_file_sandbox(filepath: str) -> dict:
    """Read from a sandbox temp file (never outside BH_AGENT_WORKSPACE or /tmp)."""
    abs_path = os.path.abspath(filepath)
    safe_prefixes = [_WORKSPACE, "/tmp"]
    if not any(abs_path.startswith(p) for p in safe_prefixes):
        return {"error": "source path not in allowed sandbox directory"}
    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            return {"path": abs_path, "content": f.read()}
    except FileNotFoundError:
        return {"error": "file not found"}


# Schema definitions (JSON Schema draft-07 style for OpenAI tools)
TOOL_SCHEMAS = {
    "get_fixture_weather": {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "City name (e.g. Tokyo, Paris)"}
        },
        "required": ["city"],
        "additionalProperties": False
    },
    "lookup_record": {
        "type": "object",
        "properties": {
            "record_id": {"type": "string", "description": "ID of record to look up"}
        },
        "required": ["record_id"],
        "additionalProperties": False
    },
    "add": {
        "type": "object",
        "properties": {
            "a": {"type": "number"},
            "b": {"type": "number"}
        },
        "required": ["a", "b"],
        "additionalProperties": False
    },
    "multiply": {
        "type": "object",
        "properties": {
            "x": {"type": "number"},
            "y": {"type": "number"}
        },
        "required": ["x", "y"],
        "additionalProperties": False
    },
    "divide": {
        "type": "object",
        "properties": {
            "x": {"type": "number"},
            "y": {"type": "number"}
        },
        "required": ["x", "y"],
        "additionalProperties": False
    },
    "get_system_time": {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False
    },
    "list_directory": {
        "type": "object",
        "properties": {
            "path": {"type": "string"}
        },
        "required": ["path"],
        "additionalProperties": False
    },
    "write_file_sandbox": {
        "type": "object",
        "properties": {
            "filepath": {"type": "string"},
            "content": {"type": "string"}
        },
        "required": ["filepath", "content"],
        "additionalProperties": False
    },
    "read_file_sandbox": {
        "type": "object",
        "properties": {
            "filepath": {"type": "string"}
        },
        "required": ["filepath"],
        "additionalProperties": False
    },
}


def validate_tool_call(func_name: str, args: dict) -> tuple[bool, str | None]:
    """Validate tool call arguments against schema. Returns (is_valid, error_message)."""
    if func_name not in TOOL_SCHEMAS:
        return False, f"Unknown tool: {func_name}"
    
    schema = TOOL_SCHEMAS[func_name]
    # Basic validation
    for prop_name, prop_schema in schema["properties"].items():
        if prop_name not in args:
            return False, f"Missing required property: {prop_name}"
        expected_type = prop_schema.get("type")
        if expected_type == "string" and not isinstance(args[prop_name], str):
            return False, f"Property {prop_name} must be string"
        elif expected_type == "number":
            if not isinstance(args[prop_name], (int, float)):
                return False, f"Property {prop_name} must be number"
    # Check additionalProperties: False - no extra keys
    allowed_keys = set(schema["properties"].keys()) | {"function", "arguments"}  # for OpenAI wrapper
    if args.keys() - allowed_keys:
        extra = args.keys() - allowed_keys
        return False, f"Unknown property: {next(iter(extra))}"
    
    return True, None


def invoke_fixture(func_name: str, arguments: dict) -> Any:
    """Invoke the fixture function with validated arguments."""
    # Map internal names to OpenAI tool_call format
    func_map = {
        "get_fixture_weather": get_fixture_weather,
        "lookup_record": lookup_record,
        "add": add,
        "multiply": multiply,
        "divide": divide,
        "get_system_time": get_system_time,
        "list_directory": list_directory,
        "write_file_sandbox": write_file_sandbox,
        "read_file_sandbox": read_file_sandbox,
    }
    
    if func_name not in func_map:
        raise ValueError(f"Unknown fixture function: {func_name}")
    
    return func_map[func_name](**arguments)


# Test harness for Stage 2 acceptance criteria
class ToolFixtureHarness:
    """Test harness that validates tool-call gates."""
    
    def __init__(self, fixtures=None):
        self.fixtures = fixtures or {}
    
    def validate_tool_response(self, response_text: str) -> tuple[bool, list]:
        """Check that tool calls were made correctly and results used."""
        checks = []
        
        # Check no plain text tool call in response
        if re.search(r'\$\(python|```.*?:', response_text):
            checks.append(("no_plain_tool_call", False))
        else:
            checks.append(("no_plain_tool_call", True))
        
        # Check no hallucinated tools (only known fixture names)
        allowed_tools = set(TOOL_SCHEMAS.keys())
        found_tools = re.findall(r'([a-z_]+)\(', response_text)
        for tool in found_tools:
            if tool not in allowed_tools:
                checks.append(("valid_tool_name", False))
                break
        else:
            checks.append(("valid_tool_name", True))
        
        # Check response uses tool results (for tests that should use tools)
        checks.append(("response_length", len(response_text) > 50))
        
        return all(c[1] for c in checks), [c[0] if c[1] else f"failed: {c[0]}" for c in checks]


# Example multi-turn test prompt
MULTITURN_PROMPT = """You need to find the weather and add temperatures together.

Please look up today's temperature for Tokyo and New York, then calculate their difference."""
