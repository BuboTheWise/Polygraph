"""
Polygraph #1 Stage 1 — CLI parse + URL-normalization end-to-end tests.

Covers (per card t_2776be27 + issue #1 acceptance):
  1. CLI parse: every flag that exists in the parser parses to the right
     type/default. `--max-error-rate` is optional (None by default, float when
     set). Invalid choices (e.g. a bad --severity) are rejected.
  2. v1.2 operating model: the identity flags --model / --base-url / --api-key /
     --provider are NOT accepted (identity comes from the profile, not the CLI).
  3. URL-normalization end-to-end: normalize_base_url() and ModelClient both
     collapse bare-host / trailing-slash / /v1-suffixed bases (plus edge cases)
     into exactly one .../v1/chat/completions endpoint. A None base_url
     (Hermes isolated profile) stays "" so the isolation layer supplies it.
"""

from __future__ import annotations

import pytest

from scripts.run_polygraph import ModelClient, normalize_base_url, parse_args


# ---------------------------------------------------------------------------
# 1. CLI parse — the flags that actually exist
# ---------------------------------------------------------------------------

def test_defaults():
    """A bare invocation yields the documented defaults."""
    a = parse_args([])
    assert a.severity == "comprehensive"
    assert a.output is None
    assert a.no_tools is False
    assert a.tests is None
    assert a.timeout is None
    assert a.stream is False
    assert a.concurrency_level == 1
    assert a.duration_seconds is None
    assert a.prompts is None
    assert a.hermes_mode is False
    # The error-rate gate is OFF by default (None), not 0.0.
    assert a.max_error_rate is None


def test_all_documented_flags_parse():
    """Every parser flag accepts a value and round-trips to the right type."""
    a = parse_args([
        "--severity", "critical",
        "--output", "out.md",
        "--no-tools",
        "--tests", "TC",
        "--timeout", "45",
        "--stream",
        "--concurrency", "4",
        "--duration", "120",
        "--prompts", "my/prompts.json",
        "--hermes",
        "--max-error-rate", "0.25",
    ])
    assert a.severity == "critical"
    assert a.output == "out.md"
    assert a.no_tools is True
    assert a.tests == "TC"
    assert a.timeout == 45.0
    assert a.stream is True
    assert a.concurrency_level == 4
    assert a.duration_seconds == 120.0
    assert a.prompts == "my/prompts.json"
    assert a.hermes_mode is True
    assert a.max_error_rate == 0.25


def test_max_error_rate_parses_to_float():
    a = parse_args(["--max-error-rate", "0.5"])
    assert isinstance(a.max_error_rate, float)
    assert a.max_error_rate == 0.5


def test_max_error_rate_zero_is_valid():
    """0.0 is a legitimate (strict) gate setting, distinct from the None default."""
    a = parse_args(["--max-error-rate", "0"])
    assert a.max_error_rate == 0.0


def test_bad_severity_rejected():
    with pytest.raises(SystemExit):
        parse_args(["--severity", "not-a-level"])


def test_bad_concurrency_rejected():
    with pytest.raises(SystemExit):
        parse_args(["--concurrency", "3"])


def test_unknown_flag_rejected():
    with pytest.raises(SystemExit):
        parse_args(["--bogus-flag", "x"])


# ---------------------------------------------------------------------------
# 2. v1.2 operating model — identity flags are NOT CLI flags
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("flag", ["--model", "--base-url", "--api-key", "--provider"])
def test_identity_flags_removed(flag):
    """v1.2: identity comes from the profile, not the CLI. These must be rejected."""
    with pytest.raises(SystemExit):
        parse_args([flag, "x"])


# ---------------------------------------------------------------------------
# 3. URL-normalization — normalize_base_url (endpoint builder)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw",
    [
        "http://localhost",
        "http://localhost/",
        "http://localhost/v1",
        "http://localhost/v1/",
        "http://127.0.0.1:11434",
        "http://127.0.0.1:11434/v1",
        "http://localhost//v1//v1/",
        "  HTTP://LOCALHOST  ",
    ],
)
def test_normalize_base_url_single_v1(raw):
    """Every form of a local base collapses to exactly one /v1 endpoint."""
    out = normalize_base_url(raw)
    assert out.endswith("/v1/chat/completions")
    # Exactly one /v1 path segment (no repeated /v1/v1).
    assert out.count("/v1/") == 1


@pytest.mark.parametrize("raw", ["", None])
def test_normalize_base_url_empty_defaults_local(raw):
    """Empty/None base_url defaults to the local Ollama endpoint — never cloud."""
    out = normalize_base_url(raw)
    assert "openai" not in out.lower()
    assert "127.0.0.1:11434" in out or "localhost" in out
    assert out.endswith("/v1/chat/completions")


# ---------------------------------------------------------------------------
# 4. URL-normalization — end-to-end through ModelClient (F10)
# ---------------------------------------------------------------------------

def _endpoint(base_url) -> str:
    """Reconstruct the endpoint ModelClient.chat() would POST to."""
    client = ModelClient(base_url=base_url, model="test", api_key="")
    return f"{client.base_url}/chat/completions"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("http://localhost", "http://localhost/v1/chat/completions"),
        ("http://localhost/", "http://localhost/v1/chat/completions"),
        ("http://localhost/v1", "http://localhost/v1/chat/completions"),
        ("http://127.0.0.1:11434", "http://127.0.0.1:11434/v1/chat/completions"),
        ("http://127.0.0.1:11434/v1", "http://127.0.0.1:11434/v1/chat/completions"),
        ("http://HOST:8080//v1//v1/", "http://host:8080/v1/chat/completions"),
    ],
)
def test_modelclient_endpoint_canonical(raw, expected):
    """F10: regardless of input form, the client POSTs to one /v1 endpoint."""
    assert _endpoint(raw) == expected


def test_modelclient_none_base_url_is_hermes_isolation():
    """A None base_url (isolated profile) stays "" — the isolation layer fills it."""
    client = ModelClient(base_url=None, model="test", api_key="")
    assert client.base_url == ""


def test_modelclient_no_double_slash():
    """The trailing-slash edge case must not produce //chat/completions."""
    ep = _endpoint("http://localhost/")
    assert "//chat" not in ep
