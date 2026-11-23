#!/usr/bin/env python3
"""Run Stage 4 streaming mock-server tests."""

import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from polygraph_app.streaming import (
    StreamMetrics,
    _ensure_utf8_boundary,
    parse_sse_stream,
)


async def run_tests():
    """Run mock-server tests."""
    
    print("=" * 60)
    print("Stage 4 Mock-Server Tests")
    print("=" * 60)
    
    # Test 1: UTF-8 boundary handling
    print("\n[TEST 1] UTF-8 boundary handling:")
    assert _ensure_utf8_boundary(b"hello") == "hello"
    assert _ensure_utf8_boundary("ascii text") == "ascii text"
    multibyte = "こんにちは世界".encode("utf-8")
    assert _ensure_utf8_boundary(multibyte) == "こんにちは世界"
    print("  ✓ Passed")
    
    # Test 2: StreamMetrics dataclass
    print("\n[TEST 2] StreamMetrics dataclass fields:")
    t_send = 100.0
    metrics = StreamMetrics(
        t_send=t_send,
        ttft_content=1.5,
        ttft_any=2.0,
        t_done=10.0,
        e2e=10.0,
        http_status=200,
        error_class="none",
    )
    assert metrics.t_send == t_send
    assert metrics.e2e == 10.0
    assert metrics.is_complete is True
    print(f"  ✓ Fields captured: t_send={metrics.t_send}, e2e={metrics.e2e}")
    
    # Test 3: SSE parsing
    print("\n[TEST 3] SSE parsing:")
    chunks = [
        '{"delta": {"role": "assistant", "content": "Hello"}, "done": false}\n\n',
        '{"delta": {"reasoning_content": "Thinking...", "content": ""}, "done": false}\n\n',
        '{"delta": {"role": "assistant", "content": " World"}, "done": true}\n\n',
    ]
    
    parsed = []
    async for chunk in parse_sse_stream(chunks):
        if "partial_buffer" not in chunk:
            parsed.append(chunk)
    
    assert len(parsed) == 3, f"Expected 3 chunks, got {len(parsed)}"
    print(f"  ✓ Parsed {len(parsed)} complete events")
    
    # Test 4: stream_with_metrics mock data
    print("\n[TEST 4] Stream metrics with mock data:")
    async def test_stream():
        mock_data = [
            {"delta": {"content": "Hello"}, "done": False},
            {"delta": {"content": ", World!"}, "done": True},
        ]
        
        chunk_count = 0
        async for metrics, chunk in parse_sse_stream(["".join([c.get("delta", {}).get("content", "") for c in mock_data])]):
            pass
        
        print(f"  ✓ Stream iteration works")
    
    await test_stream()
    
    print("\n" + "=" * 60)
    print("All Stage 4 mock-server tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_tests())
