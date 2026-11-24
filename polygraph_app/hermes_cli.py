#!/usr/bin/env python3
"""
Real Hermes CLI chat client for Polygraph hermes-mode.

Wraps the ``hermes chat --oneshot --format text`` agent-runtime invocation as a
subprocess against an isolated cloned profile. This is the "through the actual
Hermes CLI path" implementation: each test prompt is executed by the Hermes
agent runtime (the same code path an operator types into ``hermes chat``), not
a bare ``httpx`` POST to the model endpoint.

Design notes:
- One fresh oneshot session per prompt (stateless, no session bleed between tests).
- The clone is the CLI's active profile: HERMES_HOME points at the clone dir and
  HERMES_PROFILE is the clone name, so the CLI resolves the model/identity/skills
  from the clone's config.yaml.
- .env values are redacted out of captured stdout/stderr before they are stored,
  so no secrets leak into reports or manifests.
- Long timeout (>= 900s) because a cold oneshot takes several minutes.
"""

import os
import re
import shlex
import shutil
import subprocess
import asyncio
from pathlib import Path
from typing import List, Optional

from polygraph_app.hermes import read_profile_model


def _parse_env_values(env_path) -> List[str]:
    """Return the list of non-empty VALUES from a .env file (for redaction).

    Parses simple ``KEY=VALUE`` lines; ignores comments/blank lines. Values are
    the part after the first ``=``. Never returns the keys, only the secret-ish
    value strings.
    """
    p = Path(env_path)
    if not p.exists():
        return []
    vals = []
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return vals
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if not key.strip():
            continue
        value = value.strip()
        # Strip surrounding quotes if present.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            vals.append(value)
    return vals


def redact_secrets(text: str, env_path) -> str:
    """Replace any .env values found in ``text`` with ``[REDACTED]``."""
    if not text:
        return text
    for val in _parse_env_values(env_path):
        if len(val) < 3:
            continue
        text = text.replace(val, "[REDACTED]")
    return text


class HermesCLIChatClient:
    """Execute prompts through the real Hermes CLI (agent runtime subprocess).

    Usage::

        client = HermesCLIChatClient(profile_ctx)
        response = client.chat("What is 2+2?")
    """

    def __init__(
        self,
        profile_ctx,
        hermes_bin: Optional[str] = None,
        timeout: int = 900,
        cwd: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ):
        self.profile_ctx = profile_ctx
        self.hermes_bin = hermes_bin or profile_ctx.hermes_bin or find_bin_fallback()
        if not self.hermes_bin or not os.path.isfile(self.hermes_bin):
            raise RuntimeError(
                "Hermes CLI binary not found; cannot run hermes-mode through the CLI path."
            )
        self.timeout = int(timeout)
        # Run inside the clone's fixture workspace so relative file ops resolve.
        self.cwd = cwd or profile_ctx.fixtures_dir or profile_ctx.workdir or os.getcwd()
        # Expose .model / .provider so the runner's report and logs are accurate.
        # Default to the clone's config.yaml model; explicit args override.
        if model is None or provider is None:
            cm, cp = read_profile_model(profile_ctx.workdir or profile_ctx.clone_dir)
            model = model or cm
            provider = provider or cp
        self.model = model or ""
        self.provider = provider or ""
        self._env = self._build_env()

    @staticmethod
    def _build_env() -> dict:
        env = dict(os.environ)
        # (overwritten by caller via profile fields; kept here for shape)
        return env

    def _clone_env(self) -> dict:
        env = dict(os.environ)
        env["HERMES_HOME"] = str(self.profile_ctx.workdir or self.profile_ctx.clone_dir)
        env["HERMES_PROFILE"] = str(self.profile_ctx.clone_name or self.profile_ctx.clone_id)
        # Keep memory/bank from writing into the source profile.
        return env

    def build_command(self, prompt: str) -> List[str]:
        """The exact argv used for one oneshot agent turn."""
        return [
            self.hermes_bin,
            "chat",
            "-q",
            prompt,
            "--oneshot",
            "--format",
            "text",
        ]

    def describe_command(self, prompt: str) -> str:
        """Human-readable command line (with secrets redacted) for evidence."""
        argv = self.build_command(prompt)
        env_path = Path(self.profile_ctx.workdir or ".") / ".env"

        def red(s: str) -> str:
            return redact_secrets(s, env_path)

        return " ".join(shlex.quote(red(s)) if s else s for s in argv)

    async def chat(self, prompt: str, stream: bool = False, **_kw) -> str:
        """Run one oneshot agent turn and return the model's text response.

        Async-compatible with the runner's ``await client.chat(prompt, stream=...)``
        call. The blocking subprocess is dispatched to a worker thread so the
        event loop stays responsive. ``stream`` is accepted for interface
        compatibility but ignored (the CLI oneshot path is not SSE-streaming).
        """
        return await asyncio.to_thread(self._chat_sync, prompt)

    def _chat_sync(self, prompt: str) -> str:
        """Blocking execution of one oneshot agent turn (used by ``chat``).

        Raises RuntimeError on non-zero exit or timeout, with the (redacted)
        stderr tail included for diagnostics.
        """
        argv = self.build_command(prompt)
        env = self._clone_env()
        env_path = Path(self.profile_ctx.workdir or ".") / ".env"
        try:
            proc = subprocess.run(
                argv,
                env=env,
                cwd=self.cwd,
                timeout=self.timeout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except subprocess.TimeoutExpired as e:
            partial = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            partial = redact_secrets(partial, env_path)
            raise RuntimeError(
                f"hermes CLI oneshot timed out after {self.timeout}s (partial: {partial[:200]!r})"
            )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        stdout = redact_secrets(stdout, env_path)
        stderr = redact_secrets(stderr, env_path)
        if proc.returncode != 0:
            tail = stderr.strip().splitlines()[-8:]
            raise RuntimeError(
                f"hermes CLI oneshot exited {proc.returncode}: "
                + " | ".join(tail)
            )
        return extract_response_text(stdout, stderr)


def find_bin_fallback() -> Optional[str]:
    """Locate the hermes CLI (used if profile_ctx did not resolve one)."""
    try:
        from polygraph_app.hermes import find_hermes_bin
        return find_hermes_bin()
    except Exception:
        return shutil.which("hermes")


# `hermes chat --format text` wraps the model answer in a block:
#     ────────────────────────────────
#     ☤ Hermes
#     <model answer lines>
#     ────────────────────────────────
#     (optional "Resume this session with: ..." footer + metadata)
# We extract the answer as the lines after the LAST "☤ ...Hermes" marker up to
# the next full-width separator line.
_SEPARATOR_RE = re.compile(r"^\s*─{4,}\s*$")
_HERMES_MARKER_RE = re.compile(r"^\s*☤\s*.*Hermes", re.IGNORECASE)


def extract_response_text(stdout: str, stderr: str = "") -> str:
    """Return the model's text answer from captured `hermes chat` stdout.

    Looks for the ``☤ Hermes`` answer block and returns the lines between it and
    the following separator. Falls back to the whole stdout (trimmed) if the
    marker is not present (e.g. a future format change), then to stderr.
    """
    text = (stdout or "").strip()
    if not text:
        return (stderr or "").strip()

    lines = text.splitlines()
    # Find the last "☤ Hermes" marker.
    marker_idx = None
    for i, ln in enumerate(lines):
        if _HERMES_MARKER_RE.match(ln):
            marker_idx = i
    if marker_idx is not None:
        collected = []
        for ln in lines[marker_idx + 1:]:
            if _SEPARATOR_RE.match(ln):
                break
            collected.append(ln)
        answer = "\n".join(collected).strip()
        if answer:
            return answer

    # Fallback: strip obvious chrome lines, keep the rest.
    kept = [ln for ln in lines if not _SEPARATOR_RE.match(ln)]
    result = "\n".join(kept).strip()
    return result
