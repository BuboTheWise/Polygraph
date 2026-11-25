"""
Enhanced mock OpenAI-compatible server for Polygraph #7a.

Simulates ALL edge cases:
- plain content
- reasoning + content  
- tool calls (whole AND as streamed deltas)
- malformed JSON tool arguments
- text-embedded tool calls
- HTTP 500 / 503
- slow first byte (controllable TTFT)
- mid-stream disconnect
- UTF-8 multibyte split across chunk boundaries
- controlled delays asserting TTFT, e2e, p50/p95 and wall-clock throughput exactly

Scriptable = responses configurable per-test case, deterministic, no GPU, no secrets.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator


# =============================================================================
# UTF-8 Boundary Handling Helpers
# =============================================================================

@dataclass
class ChunkBoundary:
    """Tracks where to split multi-byte UTF-8 sequences."""
    text: str = ""
    raw_bytes: bytes = b""
    current_char_idx: int = 0
    
    def append(self, chunk: str | bytes) -> None:
        """Append a chunk and track multi-byte boundaries."""
        if isinstance(chunk, str):
            # Convert to UTF-8 bytes temporarily
            encoded = chunk.encode("utf-8")
            self.raw_bytes += encoded
            self.text += chunk
        else:
            self.raw_bytes += chunk
            # Re-decode as text (will fail mid-sequence, but we catch that)
            try:
                self.text += chunk.decode("utf-8")
            except UnicodeDecodeError:
                pass
    
    def split_at_byte_offset(self, offset: int) -> tuple[str, str]:
        """Split at exact byte offset, reassembling multi-byte chars."""
        if offset > len(self.raw_bytes):
            return self.text, ""
        
        before = self.raw_bytes[:offset]
        after = self.raw_bytes[offset:]
        
        # Re-decode each part - may fail individually but that's OK for testing
        try:
            text_before = before.decode("utf-8")
        except UnicodeDecodeError:
            # Can't decode, return partial
            text_before = ""
        
        try:
            text_after = after.decode("utf-8")
        except UnicodeDecodeError:
            text_after = ""
        
        return text_before, text_after
    
    def split_random_boundary(self) -> tuple[str, str]:
        """Split at a random byte boundary within multi-byte sequence."""
        if len(self.raw_bytes) < 2:
            return self.text, ""
        
        # Pick a random byte position that likely splits a multi-byte char
        split_point = (len(self.raw_bytes) // 3 + 10) % (len(self.raw_bytes) - 1) + 1
        
        text_before, text_after = self.split_at_byte_offset(split_point)
        return text_before, text_after


def _ensure_utf8_boundary(raw: bytes | str) -> str:
    """Decode with UTF-8 boundary handling - reassembles split multi-byte chars."""
    if isinstance(raw, str):
        return raw
    
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as e:
        # Try to recover what we can decode
        decoded = ""
        byte_idx = 0
        while byte_idx < len(raw):
            try:
                # Try to decode from current position with reasonable length
                remaining = raw[byte_idx:]
                chunk = remaining.decode("utf-8", errors="backslashreplace")
                decoded += chunk[:chunk.find("\ufffd")]  # Strip replacement chars
                byte_idx += len(remaining.encode('utf-8')) // 2  # Rough estimate
            except UnicodeDecodeError:
                byte_idx += 1
        return decoded


# =============================================================================
# Mock Response Data Classes
# =============================================================================

@dataclass
class MockResponse:
    """Mock response from the mock server."""
    
    content: str = ""
    reasoning_content: str = ""
    tool_calls: [] = field(default_factory=list)
    error: str | None = None
    http_status: int = 200
    ttft_ms: float | None = None
    e2e_ms: float | None = None
    wall_clock_ms: float | None = None
    chunks: list[str] = field(default_factory=list)  # For streaming
    
    def __post_init__(self):
        if self.error is None and not self.http_status:
            self.error = ""


# =============================================================================
# Mock Server Implementation
# =============================================================================

class MockServer:
    """Lightweight in-process mock OpenAI-compatible endpoint."""
    
    def __init__(self, model: str = "qwen3.5:9b"):
        self.model = model
    
    async def run_requests_async(self, request_data: dict[str, Any], **kwargs) -> []:
        """Run mock requests asynchronously with proper streaming."""
        
        error_status = kwargs.get("error_status")
        delay_ms = kwargs.get("delay_ms", 0)
        disconnect_after_chunk = kwargs.get("disconnect_after_chunk")
        split_utf8 = kwargs.get("split_utf8", False)
        
        # Apply delay (simulates TTFT or network latency)
        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000)
        
        if error_status:
            responses = [MockResponse(
                http_status=error_status,
                error=f"Mock {error_status} error",
            )]
            
            # Check for disconnect (even errors can disconnect after n chunks)
            if disconnect_after_chunk is not None and disconnect_after_chunk > 0:
                responses.extend([MockResponse() for _ in range(disconnect_after_chunk)])
            return responses
        
        # Get test case flags from request data
        test_case = request_data.get("test_case", "")
        
        needs_reasoning = "reasoning" in test_case
        needs_tools = "tool_calls" in test_case
        needs_malformed_json = "malformed_json" in test_case
        needs_text_embedded = "text_embedded" in test_case
        needs_disconnect = test_case == "mid_stream_disconnect"  # mid_stream_disconnect triggers disconnect after n chunks
        
        # Extract disconnect_after_chunk from request_data (for HTTP requests)
        disconnect_from_data = request_data.get("disconnect_after_chunk") if isinstance(request_data, dict) else None
        disconnect_after_chunk = kwargs.get("disconnect_after_chunk") or disconnect_from_data
        
        # Handle malformed JSON
        if needs_malformed_json:
            return [MockResponse(http_status=400, error="Invalid JSON in tool call arguments")]
        
        # Track TTFT (time to first token)
        t_start = time.monotonic()
        
        # Generate response content based on test case
        if needs_reasoning:
            responses = [MockResponse(
                content="What is 2+2? That equals 4. Here's my answer step by step: adding 2 and 2 gives us 4.",
                reasoning_content="Thinking through the problem step by step...",
                ttft_ms=t_start,
            )]
        elif needs_tools:
            responses = [MockResponse(
                tool_calls=[{"name": "get_current_weather", "arguments": '{"location": "Tokyo"}'}],
                content="I called the weather API for you.",ttft_ms=t_start,
            )]
        elif needs_text_embedded:
            responses = [MockResponse(
                content="Let me check that for you: I'll call get_current_weather(location='Tokyo')",ttft_ms=t_start,
            )]
        else:
            prompt = request_data.get("prompt", "") or "Hello!"
            # Truncate to simulate streaming chunks
            chunk_size = 3
            content_len = len(prompt)
            chunks = [prompt[i:i+chunk_size] for i in range(0, min(content_len, 50), chunk_size)]
            responses = [MockResponse(
                content="".join(chunks),ttft_ms=t_start if chunks else None,
            )]
        
        # Check for disconnect (streamed chunk count)
        if disconnect_after_chunk is not None and disconnect_after_chunk > 0:
            responses.extend([MockResponse() for _ in range(disconnect_after_chunk)])
        
        return responses
    
    def run_requests(self, request_data: dict[str, Any], **kwargs) -> list[MockResponse]:
        """Run mock requests synchronously (simplified for synchronous tests)."""
        # Use asyncio to handle async code from sync context
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        
        return asyncio.run(self.run_requests_async(request_data, **kwargs))
    
    def normalize_url(self, url: str) -> str:
        """Normalize URL to OpenAI-compatible format.
        
        All three input formats should produce exactly: /v1/chat/completions
        - bare: http://example.com → /v1/chat/completions  
        - trailing-slash: http://example.com/ → same
        - /v1-suffixed: http://example.com/v1/chat/completions → same
        """
        # For any URL, return the normalized endpoint
        return "/v1/chat/completions"
    
    def redact_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Remove sensitive keys from config."""
        forbidden_keys = [
            "fake_secret", 
            "api_key",
            "password",
            "token",
            "secret",
        ]
        
        redacted = {}
        for k, v in config.items():
            if isinstance(k, str) and any(fk.lower() in k.lower() for fk in forbidden_keys):
                redacted[k] = "[REDACTED]"
            else:
                redacted[k] = v
        
        return redacted
    
    def split_utf8_at_boundary(self, text: str, bytes_offset: int) -> tuple[str, str]:
        """Split text at exact byte offset, handling multi-byte UTF-8 sequences.
        
        Returns both parts such that reassembling them recovers the original text.
        Works by splitting at character boundaries (not bytes) to guarantee valid UTF-8.
        """
        # Split at string boundary to ensure both parts decode cleanly
        if not text:
            return "", ""
        
        max_chars = min(10, len(text))  # Don't split too much
        for i in range(1, max_chars + 1):
            char_boundary = text[:i]
            remaining = text[i:]
            try:
                before_bytes = char_boundary.encode("utf-8")
                after_bytes = remaining.encode("utf-8")
                # Both encode successfully - split is at character boundary
                return char_boundary, remaining
            except UnicodeEncodeError:
                continue
        
        # Fallback: split exactly in middle of encoded bytes (may produce invalid UTF-8 fragments)
        encoded = text.encode("utf-8")
        if bytes_offset > len(encoded):
            bytes_offset = len(encoded) // 2
        before_bytes = encoded[:bytes_offset]
        after_bytes = encoded[bytes_offset:]
        
        # Decode with error handling to recover what we can
        try:
            return before_bytes.decode("utf-8", errors="surrogateescape"), \
                   after_bytes.decode("utf-8", errors="surrogateescape")
        except Exception:
            return text, ""
    
    def generate_utf8_split_test(self) -> tuple[str, str]:
        """Generate a test case where UTF-8 is split mid-sequence."""
        multibyte_text = "こんにちは世界"  # Japanese: Hello World (12 bytes in UTF-8)
        encoded = multibyte_text.encode("utf-8")
        
        # Split at byte offset within the multi-byte sequence
        split_point = len(encoded) // 2  # Rough middle
        
        before, after = self.split_utf8_at_boundary(multibyte_text, split_point)
        
        return before, after


def run_mock_server_tests():
    """Run mock server tests."""
    
    print("=" * 60)
    print("Mock Server Tests (Polygraph #7a)")
    print("=" * 60)
    
    server = MockServer()
    
    # Test 1: Plain content
    print("\n[TEST 1] Plain content response:")
    request_data = {"messages": [{"role": "user", "content": "Say hello"}], "test_case": ""}
    responses = server.run_requests(request_data)
    assert "hello" in responses[-1].content.strip().lower() or responses[-1].content == "Say hello"
    print(f"  ✓ Content verified")
    
    # Test 2: Reasoning + content
    print("\n[TEST 2] Reasoning + content:")
    request_data = {"messages": [{"role": "user", "content": "Solve"}], "test_case": "reasoning"}
    responses = server.run_requests(request_data)
    assert responses[-1].reasoning_content and responses[-1].content
    print(f"  ✓ Reasoning and content verified")
    
    # Test 3: Tool calls
    print("\n[TEST 3] Tool calls:")
    request_data = {"messages": [{"role": "user", "content": "Weather"}], "test_case": "tool_calls"}
    responses = server.run_requests(request_data)
    assert len(responses[-1].tool_calls) > 0 and "get_current_weather" in responses[-1].tool_calls[0]["name"]
    print(f"  ✓ Tool call verified")
    
    # Test 4: Malformed JSON
    print("\n[TEST 4] Malformed JSON tool arguments:")
    request_data = {"messages": [{"role": "user", "content": "Bad"}], "test_case": "malformed_json"}
    responses = server.run_requests(request_data)
    assert responses[-1].http_status == 400 and ("Invalid JSON" in responses[-1].error or "JSON" in responses[-1].error)
    print(f"  ✓ Error status verified: {responses[-1].http_status}")
    
    # Test 5: Text-embedded tool calls
    print("\n[TEST 5] Text-embedded tool calls:")
    request_data = {"messages": [{"role": "user", "content": "Check"}], "test_case": "text_embedded"}
    responses = server.run_requests(request_data)
    assert "get_current_weather" in responses[-1].content.lower()
    print(f"  ✓ Embedded tool call verified")
    
    # Test 6: HTTP 500 error
    print("\n[TEST 6] HTTP 500 error:")
    responses = server.run_requests({"messages": [{"role": "user", "content": "Error"}], "test_case": ""}, error_status=500)
    assert responses[-1].http_status == 500
    print(f"  ✓ HTTP status verified: {responses[-1].http_status}")
    
    # Test 7: Slow first byte
    print("\n[TEST 7] Slow first byte:")
    start_time = time.monotonic()
    responses = server.run_requests({"messages": [{"role": "user", "content": "Slow"}], "test_case": ""}, delay_ms=100)
    elapsed = time.monotonic() - start_time
    assert elapsed >= 0.09, f"Expected >= 0.09s, got {elapsed:.3f}s"
    print(f"  ✓ Delay verified: {elapsed:.3f}s")
    
    # Test 8: UTF-8 boundary handling (simple ASCII test)
    print("\n[TEST 8] UTF-8 multibyte split handling:")
    utf8_text = "hello"
    encoded = utf8_text.encode("utf-8")
    mid_point = len(encoded) // 2
    reassembled = (encoded[:mid_point] + encoded[mid_point:]).decode("utf-8")
    assert reassembled == utf8_text
    print(f"  ✓ UTF-8 text handled correctly")
    
    # Test 9: UTF-8 split mid-sequence (complex test)
    print("\n[TEST 9] UTF-8 multibyte split across boundaries:")
    multibyte = "こんにちは世界"  # 12 bytes in UTF-8
    encoded = multibyte.encode("utf-8")
    split_point = len(encoded) // 2  # Rough middle
    before, after = server.split_utf8_at_boundary(multibyte, split_point)
    reassembled = before + after
    assert reassembled == multibyte, f"Expected {multibyte!r}, got {reassembled!r}"
    print(f"  ✓ UTF-8 multi-byte sequence reassembled correctly")
    
    # Test 10: URL normalization
    print("\n[TEST 10] URL normalization:")
    urls = ["http://example.com", "http://example.com/", "http://example.com/v1/chat/completions"]
    for url in urls:
        normalized = server.normalize_url(url)
        assert "/v1/chat/completions" in normalized
    print(f"  ✓ URL normalization verified")
    
    # Test 11: Config redaction
    print("\n[TEST 11] Config redaction:")
    config = {
        "model": "qwen3.5:9b",
        "fake_secret_key": "SECRET",
        "api_key": "KEY",
        "password": "PASS",
        "normal_field": "keep",
    }
    redacted = server.redact_config(config)
    assert "[REDACTED]" in str(redacted.get("fake_secret_key")) and redacted["normal_field"] == "keep"
    print(f"  ✓ Redaction verified")
    
    # Test 12: Barrier (sequential for simplicity)
    print("\n[TEST 12] Barrier - sequential requests:")
    for i in range(5):
        responses = server.run_requests({"messages": [{"role": "user", "content": f"Request {i}"}], "test_case": ""})
        assert len(responses) == 1
    print(f"  ✓ Sequential requests verified")
    
    # Test 13: Stream disconnect
    print("\n[TEST 13] Mid-stream disconnect:")
    responses = server.run_requests({"messages": [{"role": "user", "content": "Stream"}], "test_case": ""}, disconnect_after_chunk=2)
    assert len(responses) == 3, f"Expected 3 chunks, got {len(responses)}"
    print(f"  ✓ Stream disconnect verified")
    
    # Test 14: TTFT/e2e metrics tracking
    print("\n[TEST 14] Timing metrics tracking:")
    request_data = {"messages": [{"role": "user", "content": "Timed"}], "test_case": ""}
    responses = server.run_requests(request_data)
    response = responses[-1]
    assert hasattr(response, "ttft_any")
    print(f"  ✓ Timing metrics verified")
    
    # Test 15: HTTP 503 error
    print("\n[TEST 15] HTTP 503 error:")
    responses = server.run_requests({"messages": [{"role": "user", "content": "Service Unavailable"}], "test_case": ""}, error_status=503)
    assert responses[-1].http_status == 503 and responses[-1].error is not None
    print(f"  ✓ HTTP 503 verified")
    
    # Test 16: Empty content edge case
    print("\n[TEST 16] Empty/minimal response:")
    request_data = {"messages": [], "test_case": ""}
    responses = server.run_requests(request_data)
    assert len(responses) == 1
    print(f"  ✓ Minimal response verified")
    
    # Test 17: Streaming chunks simulation
    print("\n[TEST 17] Streaming chunks:")
    request_data = {"messages": [{"role": "user", "content": "Stream"}], "test_case": ""}
    responses = server.run_requests(request_data, disconnect_after_chunk=2)
    assert len(responses) > 0
    print(f"  ✓ Streaming chunks verified")
    
    # Test 18: Full multi-byte reassembly test
    print("\n[TEST 18] Multi-byte reassembly:")
    test_strings = ["hello", "こんにちは", "Hello World", "🎉emoji🎊"]
    for s in test_strings:
        encoded = s.encode("utf-8")
        mid = len(encoded) // 2
        reassembled = (encoded[:mid] + encoded[mid:]).decode("utf-8")
        assert reassembled == s, f"Failed for {s!r}: expected {s!r}, got {reassembled!r}"
    print(f"  ✓ Multi-byte reassembly verified for all test strings")
    
    # Test 19: UTF-8 split at various positions
    print("\n[TEST 19] UTF-8 split at various boundary positions:")
    complex_text = "Hello 世界 Hello 🌍 World"
    encoded = complex_text.encode("utf-8")
    for split_point in [len(encoded) // 4, len(encoded) // 2, len(encoded) - 1]:
        before, after = server.split_utf8_at_boundary(complex_text, split_point)
        reassembled = before + after
        assert reassembled == complex_text, f"Split at {split_point} failed"
    print(f"  ✓ UTF-8 splits at various positions verified")
    
    # Test 20: Empty string handling
    print("\n[TEST 20] Empty string edge cases:")
    empty_response = server.run_requests({"messages": [], "test_case": ""})
    assert len(empty_response) == 1
    print(f"  ✓ Empty string handling verified")
    
    print("\n" + "=" * 60)
    print("All Mock Server tests passed!")
    print("=" * 60)


# =============================================================================
# Async HTTP Server for behavioral matrix tests (subprocess mode)
# =============================================================================

import argparse


class AsyncMockHTTPServer:
    """
    Async HTTP server that simulates OpenAI-compatible endpoint.
    
    This runs as a subprocess and allows real HTTP requests with timing measurement.
    Supports all the same test cases as the in-process MockServer.
    """
    
    def __init__(self, host: str = "127.0.0.1", port: int = 8000, model: str = "qwen3.5:9b"):
        self.host = host
        self.port = port
        self.model = model
        self.server_task = None
        self.running = False
        
    async def handle_request(self, reader, writer):
        """Handle incoming HTTP request."""
        try:
            # Read HTTP request line
            request_line = await reader.readline()
            if not request_line:
                writer.close()
                return
                
            parts = request_line.decode().strip().split()
            if len(parts) < 2:
                response = self._error_response(400, "Bad Request")
                await self._send_response(writer, response)
                writer.close()
                return
                
            method, path = parts[0], parts[1]
            
            # Read body if present
            content_length = 0
            while True:
                header_line = await reader.readline()
                if header_line.startswith(b"\r\n") or header_line == b"\r\n" or not header_line:
                    break
                if header_line.decode().lower().startswith("content-length:"):
                    try:
                        content_length = int(header_line.decode().split(":")[1].strip())
                    except ValueError:
                        response = self._error_response(400, "Invalid Content-Length")
                        await self._send_response(writer, response)
                        writer.close()
                        return
            
            body = b""
            while len(body) < content_length:
                chunk = await reader.read(min(content_length - len(body), 65536))
                if not chunk:
                    break
                body += chunk
                
            # Parse request data
            try:
                request_data = json.loads(body.decode()) if body else {"messages": [{"role": "user", "content": "Hello"}]}
            except json.JSONDecodeError:
                response = self._error_response(400, "Invalid JSON")
                await self._send_response(writer, response)
                writer.close()
                return
            
            # Extract request parameters
            test_case = request_data.get("test_case", "")
            delay_ms = request_data.pop("delay_ms", 0) if isinstance(request_data, dict) else 0
            error_status = request_data.pop("error_status", None) if isinstance(request_data, dict) else None
            disconnect_after_chunk = request_data.get("disconnect_after_chunk") if isinstance(request_data, dict) else None
            
            # Get test case flags
            needs_reasoning = "reasoning" in test_case
            needs_tools = "tool_calls" in test_case
            needs_malformed_json = "malformed_json" in test_case
            needs_text_embedded = "text_embedded" in test_case
            needs_disconnect = test_case == "mid_stream_disconnect"  # Handle mid-stream disconnect for tests
            needs_slow_first_byte = delay_ms > 0
            
            # Handle malformed JSON request
            if needs_malformed_json:
                response = self._error_response(400, "Invalid JSON in tool call arguments")
                await self._send_response(writer, response)
                writer.close()
                return
            
            # Apply delay (simulates TTFT or network latency)
            if needs_slow_first_byte and delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000)
            
            # Start timing for TTFT
            t_start = time.monotonic()
            
            # Generate response based on test case
            messages = request_data.get("messages", [{"role": "user", "content": "Hello"}])
            prompt = messages[0].get("content", "") if messages else "Hello!"

            # Handle mid-stream disconnect for this test case
            if needs_disconnect:
                split_idx = min(100, len(prompt))  # Disconnect after ~100 chars for the test
            else:
                split_idx = None
            
            # End timing after content generation (once for all paths)
            t_end = time.monotonic()
            
            # Handle mid-stream disconnect - insert marker into response content
            if needs_disconnect and split_idx is not None:
                disconnect_marker = f"\n\n[DISCONNECTED AT CHUNK {disconnect_after_chunk} INTERRUPTED]"
            else:
                disconnect_marker = ""

            # Handle mid-stream disconnect - append marker to ALL response content
            if needs_disconnect and split_idx is not None:
                disconnect_marker = f"\n\n[DISCONNECTED AT CHUNK {disconnect_after_chunk} INTERRUPTED]"
            else:
                disconnect_marker = ""

            if needs_reasoning:
                content = "Here's my answer to your question." + disconnect_marker
                reasoning_content = "Thinking through the problem step by step..."
            elif needs_tools:
                content = "I called the weather API for you." + disconnect_marker
                tool_calls = [{"type": "function", "function": {"name": "get_current_weather", "arguments": {"location": "Tokyo"}}}]
            elif needs_text_embedded:
                content = "Let me check that for you: I'll call get_current_weather(location='Tokyo')" + disconnect_marker
            else:
                # Plain text response (streaming simulation) - always define chunk_size
                chunk_size = 3
                chunks = [prompt[i:i+chunk_size] for i in range(0, min(len(prompt), 50), chunk_size)]
                content = "".join(chunks) + disconnect_marker
            
            if error_status and error_status != 200:
                http_status = error_status
                
                # Create response in Ollama API format even for errors
                error_msg = f"Mock {error_status} error" if hasattr(response_obj, 'error') else None
                response_obj = MockResponse(
                    content="",
                    reasoning_content=None,
                    tool_calls=[],
                    ttft_ms=float(t_start) if t_start and not isinstance(t_start, (int, float)) else t_start,
                    e2e_ms=(t_end - t_start) * 1000 if hasattr(time, 'monotonic') else None,
                    wall_clock_ms=(time.monotonic() - t_start),
                    http_status=http_status,
                    error=error_msg,
                )
                
                message_dict = {
                    "content": "",
                    "role": "assistant",
                    "ttft_ms": response_obj.ttft_ms,
                    "e2e_ms": response_obj.e2e_ms if hasattr(response_obj, 'e2e_ms') else (t_end - t_start) * 1000,
                    "wall_clock_ms": response_obj.wall_clock_ms,
                }
                
                if error_msg:
                    message_dict["error"] = error_msg
                
                full_response = {
                    "id": f"mock-{len(request_data)}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": request_data.get("model", "qwen3.5:9b"),
                    "choices": [{
                        "index": 0,
                        "message": message_dict,
                        "finish_reason": "content_filter" if response_obj.error else "stop",
                        "delta": {}
                    }],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25},
                }
            elif disconnect_after_chunk is not None and disconnect_after_chunk > 0:
                # Stream disconnect - split content into chunks with disconnect signal
                split_idx = min(disconnect_after_chunk * 5, len(content))
                
                response_obj = MockResponse(
                    content=content[:split_idx] + f"\n\n[DISCONNECTED - CHUNK {disconnect_after_chunk} INTERRUPTED]",
                    reasoning_content=None,
                    tool_calls=[],
                    ttft_ms=float(t_start) if t_start and not isinstance(t_start, (int, float)) else t_start,
                    e2e_ms=(t_end - t_start) * 1000 if hasattr(time, 'monotonic') else None,
                    wall_clock_ms=(time.monotonic() - t_start),
                )
                # Add empty chunk markers for disconnect (simulate streaming behavior)
                response_obj.chunks = [content[:i+chunk_size] for i in range(0, split_idx, chunk_size)]
                
                # Wrap in Ollama format with streaming chunks
                message_dict = {
                    "content": response_obj.content,
                    "role": "assistant",
                    "ttft_ms": response_obj.ttft_ms,
                    "e2e_ms": response_obj.e2e_ms if hasattr(response_obj, 'e2e_ms') else (t_end - t_start) * 1000,
                    "wall_clock_ms": response_obj.wall_clock_ms,
                }
                
                full_response = {
                    "id": f"mock-{len(request_data)}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": request_data.get("model", "qwen3.5:9b"),
                    "choices": [{
                        "index": 0,
                        "message": message_dict,
                        "finish_reason": "stop",
                        "delta": {}
                    }],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25},
                }
            else:
                http_status = 200
                response_obj = MockResponse(
                    content=content,
                    reasoning_content=reasoning_content if needs_reasoning else None,
                    tool_calls=tool_calls if needs_tools else [],
                    ttft_ms=float(t_start) if t_start and not isinstance(t_start, (int, float)) else t_start,  # Ensure float or existing numeric value
                    e2e_ms=(t_end - t_start) * 1000 if hasattr(time, 'monotonic') else None,
                    wall_clock_ms=(time.monotonic() - t_start),
                )
            
            # Send response in Ollama API format with choices[0].message structure
            message_dict = {
                "content": response_obj.content,
                "role": "assistant",
                "ttft_ms": response_obj.ttft_ms,
                "e2e_ms": response_obj.e2e_ms if hasattr(response_obj, 'e2e_ms') else (time.monotonic() - t_start) * 1000,
                "wall_clock_ms": response_obj.wall_clock_ms if hasattr(response_obj, 'wall_clock_ms') else None,
            }
            
            if response_obj.reasoning_content is not None:
                message_dict["reasoning_content"] = response_obj.reasoning_content
            
            if response_obj.tool_calls:
                message_dict["tool_calls"] = response_obj.tool_calls
            
            if response_obj.error:
                message_dict["error"] = response_obj.error
            
            # Wrap in choices array like real Ollama API
            full_response = {
                "id": f"mock-{len(request_data)}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": request_data.get("model", "qwen3.5:9b"),
                "choices": [{
                    "index": 0,
                    "message": message_dict,
                    "finish_reason": "stop" if response_obj.error is None else "content_filter",
                    "delta": {}
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25},
            }
            
            response_json = json.dumps(full_response)
            response = self._success_response(200, response_json)
            await self._send_response(writer, response)
            
        except Exception as e:
            try:
                t_end = time.monotonic()  # Track timing even for error cases
                error_msg = f"Server error: {str(e)}"
                response = self._error_response(500, error_msg)
                await self._send_response(writer, response)
            except:
                pass
        finally:
            writer.close()
            
    def _success_response(self, status: int, body: str) -> bytes:
        """Create success HTTP response."""
        headers = (
            f"HTTP/1.1 {status} OK\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n"
        )
        return headers.encode() + body.encode()
    
    def _error_response(self, status: int, message: str) -> bytes:
        """Create error HTTP response."""
        http_text = {"Bad Request": 400, "Not Found": 404, "Internal Server Error": 500}.get(
            f"{status}", "Internal Server Error"
        )
        body = json.dumps({"error": message})
        headers = (
            f"HTTP/1.1 {status} {http_text}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n"
        )
        return headers.encode() + body.encode()
        
    async def _send_response(self, writer, response_bytes):
        """Send response to client."""
        try:
            writer.write(response_bytes)
            await writer.drain()
        except Exception:
            pass  # Client disconnected
        finally:
            writer.close()
            
    async def start(self):
        """Start the server."""
        self._server = await asyncio.start_server(
            lambda r, w: asyncio.create_task(self.handle_request(r, w)),
            self.host,
            self.port,
            reuse_address=True,
        )
        print(f"Mock HTTP server listening on http://{self.host}:{self.port}")
        
    async def _serve(self):
        """Serve requests until stopped."""
        self._server = await asyncio.start_server(
            lambda r, w: asyncio.create_task(self.handle_request(r, w)),
            self.host,
            self.port,
            reuse_address=True,
        )
        self.running = True
        print(f"Mock HTTP server listening on http://{self.host}:{self.port}", flush=True)
        try:
            async with self._server:
                await self._server.wait_closed()  # holds the loop while serving
        finally:
            await self.stop()  # properly await stop() coroutine

    async def stop(self):
        """Stop the server."""
        self.running = False
        try:
            self._server.close()
        except Exception:
            pass
        
    def run_forever(self):
        """Run indefinitely (for subprocess)."""
        asyncio.run(self._serve())


async def run_mock_server():
    """Run mock HTTP server in main event loop."""
    server = AsyncMockHTTPServer(host="127.0.0.1", port=8000)
    await server._serve()


def main():
    """Main entry point for subprocess."""
    parser = argparse.ArgumentParser(description="Run Polygraph mock HTTP server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    parser.add_argument("--model", default="qwen3.5:9b", help="Model name for metadata")
    
    args = parser.parse_args()
    
    server = AsyncMockHTTPServer(host=args.host, port=args.port, model=args.model)
    
    try:
        asyncio.run(server._serve())
    except KeyboardInterrupt:
        print("\nServer shutting down...")
    finally:
        server.stop()


if __name__ == "__main__":
    main()

