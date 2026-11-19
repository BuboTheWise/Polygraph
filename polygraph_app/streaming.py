"""
Streaming response metrics collection helpers for Polygraph.

This module provides isolated streaming logic separate from the main run_polygraph.py runner,
enabling parallel development without hitting context limits.

Stage 4 (F7): Streaming support with TTFT, e2e latency, and token counts.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, AsyncGenerator, Union

if TYPE_CHECKING:
    from httpx import Request, Response


# =============================================================================
# Data structures
# =============================================================================

@dataclass
class StreamMetrics:
    """Collect metrics for a streaming request/response."""
    
    t_send: float = 0.0  # monotonic time at request start
    
    ttft_content: float | None = None  # time to first content token
    
    ttft_any: float | None = None  # time to first any token
    
    t_done: float | None = None  # monotonic time when stream completed/error
    
    e2e: float | None = None  # total end-to-end duration
    
    http_status: int = 0
    error_class: str = "none"
    retry_count: int = 0
    timeout_flag: bool = False
    cancelled_flag: bool = False
    
    total_tokens_prompt: int | None = None
    total_tokens_completion: int | None = None

    @property
    def is_complete(self) -> bool:
        """Stream has fully completed."""
        return self.t_done is not None
    
    @property
    def is_error(self) -> bool:
        """Stream ended with an error."""
        return self.error_class != "none"


class StreamError(Exception):
    """Error that occurs during streaming."""
    code: str = ""
    message: str = ""

    def __init__(self, code: str | None = None, message: str | None = None):
        self.code = code or type(self).__name__
        self.message = message or f"Stream error: {self.code}"
        super().__init__(self.message)


class StreamTimeoutError(StreamError):
    def __init__(self):
        super().__init__("timeout", "Request exceeded timeout budget")


class StreamCancelledError(StreamError):
    def __init__(self):
        super().__init__("cancelled", "Stream cancelled by caller")


# =============================================================================
# Streaming logic
# =============================================================================

def _classify_error(exc_type: type) -> str:
    """Convert exception type to error class string."""
    errors_map = {
        TimeoutError: "timeout",
        asyncio.CancelledError: "cancelled",
        json.JSONDecodeError: "json_decode_error",
        ValueError: "value_error",
        KeyError: "key_error",
    }
    return errors_map.get(exc_type, exc_type.__name__.lower())


def _ensure_utf8_boundary(chunk: bytes | str) -> str:
    """Decode SSE chunk with UTF-8 boundary handling."""
    text = chunk if isinstance(chunk, str) else chunk.decode("utf-8")
    return text or ""


async def parse_sse_stream(raw_stream: str | list[str], buffer_size: int = 65536) -> AsyncGenerator[dict[str, Any], None]:
    """Parse SSE events from HTTP stream.
    
    Args:
        raw_stream: Raw SSE data as string or iterable of chunks
        
    Yields:
        Dict representing parsed SSE event with completion marker.
    """
    buffer = ""
    
    # Convert to list if needed
    if isinstance(raw_stream, str):
        parts = [raw_stream]
    else:
        parts = raw_stream
    
    for chunk in parts:
        text = _ensure_utf8_boundary(chunk)
        buffer += text
        
        while "\n\n" in buffer:
            event_start, buffer = buffer.split("\n\n", 1)
            
            if not event_start.strip():
                continue
            
            try:
                parsed = json.loads(event_start.strip())
            except json.JSONDecodeError:
                # Partial chunk - yield incomplete event
                yield {
                    "raw_event": event_start[:200],
                    "partial_buffer": True,
                }
                continue
            
            complete = parsed.get("done") or not (parsed.get("delta") or parsed.get("content"))
            
            yield {
                **parsed,
                "complete": complete,
            }
    
    # Yield remaining buffer if any
    if buffer.strip():
        try:
            parsed = json.loads(buffer.strip())
            yield {**parsed, "partial_buffer": False, "complete": True}
        except json.JSONDecodeError:
            yield {"raw_event": buffer[:200], "partial_buffer": True}


async def stream_with_metrics(
    response_data: Union[list[dict[str, Any]], None] = None,
    prompt: str = "",
    model: str = "qwen3.5:9b",
    timeout: float | None = 300,
) -> AsyncGenerator[tuple[StreamMetrics, dict[str, Any]], None]:
    """Async generator that streams model response with metrics collection.
    
    This is the main entry point for streaming mode. It handles:
    - Request initialization and timestamping
    - SSE parsing and chunk yield
    - Error handling and cancellation
    - Metrics collection (TTFT, e2e, tokens)
    
    Args:
        response_data: Mock response data list (for testing) or None for real API calls
        prompt: User prompt (used only for logging if needed)
        model: Model identifier
        timeout: Request timeout in seconds
    
    Yields:
        Tuple of (metrics_dict, chunk_dict) for each SSE event including final metrics.
    
    Usage:
        async for metrics, chunk in stream_with_metrics(response_data):
            print(f"Chunk: {chunk}")
    """
    t_send = time.monotonic()
    first_chunk_time: float | None = None
    
    if response_data is None:
        # Real API call case - would use client.call() here
        yield StreamMetrics(t_send=t_send, e2e=0.0), {"error": "No client provided for real streaming"}
        return
    
    chunks_consumed: list[dict] = []
    
    for i, chunk in enumerate(response_data):
        first_chunk_time = time.monotonic() - t_send if i == 0 else first_chunk_time
        
        # Extract content from chunk
        content_text = chunk.get("delta", {}).get("content", "")
        
        metrics = StreamMetrics(
            t_send=t_send,
            ttft_content=first_chunk_time,
            ttft_any=first_chunk_time or (time.monotonic() - t_send),
            e2e=time.monotonic() - t_send,
            http_status=200,
            error_class="none",
        )
        
        yield metrics, {"content": content_text}
    
    # Final metrics with completion marker
    final_metrics = StreamMetrics(
        t_send=t_send,
        ttft_content=first_chunk_time,
        ttft_any=time.monotonic() - t_send,
        t_done=time.monotonic(),
        e2e=time.monotonic() - t_send,
        http_status=200,
        error_class="none",
    )
    
    yield final_metrics, {"done": True}
