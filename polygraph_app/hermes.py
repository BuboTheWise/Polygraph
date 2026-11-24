#!/usr/bin/env python3
"""
Stage 6: Hermes end-to-end mode with isolated test profiles.

Provides:
- A fully functional profile clone from a source profile (config.yaml, .env,
  identity, skills) placed where the Hermes CLI can resolve it, so test prompts
  run through the REAL agent runtime (hermes chat) — not a raw model POST.
- Source profile treated as read-only with checksum verification
- .env copying without logging secrets
- Unique bank/profile IDs or memory disable for clones
- Per-profile fixture workspace directories
- Hermes CLI discovery + clone cleanup + source-unchanged verification

This module deliberately does NOT start any gateway/cron for test profiles:
the CLI runs in --oneshot mode, so no persistent daemons are spawned and the
source profile's state DB is never written (the clone gets a fresh state DB on
first CLI run), which keeps the run free of DB-lock contention.
"""

import os
import sys
import shutil
import hashlib
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List


# Files copied (if present) into a test-profile clone so the Hermes CLI can
# resolve the model, identity and skills. Heavy, regenerable state is
# deliberately NOT copied: the clone starts with a fresh state.db on first CLI
# run, which is what keeps the source state.db free of lock contention.
CLONE_FILES = [
    "config.yaml",
    ".env",
    "SOUL.md",
    "profile.yaml",
    "memchorus.yaml",
    "context_length_cache.yaml",
    ".skills_prompt_snapshot.json",
]
CLONE_DIRS = [
    "skills",
]


@dataclass
class ProfileIsolationContext:
    """Context for an isolated Hermes test profile."""
    source_profile: str
    clone_id: str
    workdir: Optional[str] = None            # = clone directory (absolute)
    clone_dir: Optional[str] = None          # alias for workdir
    clone_name: Optional[str] = None         # basename of clone dir (HERMES_PROFILE)
    isolated_base_url: Optional[str] = None  # CLI resolves model from clone config.yaml
    bank_id: Optional[str] = None
    profile_id: Optional[str] = None
    is_memory_disabled: bool = False
    fixtures_dir: Optional[str] = None
    source_env_checksum: str = ""            # SHA-256 (first 16 hex) of source .env before clone
    hermes_bin: Optional[str] = None         # resolved hermes CLI path
    cloned_files: List[str] = field(default_factory=list)
    hermes_home: Optional[str] = None        # profiles parent (for cleanup safety)

    def to_dict(self) -> dict:
        """JSON-safe summary (no secrets)."""
        return {
            "source_profile": self.source_profile,
            "clone_id": self.clone_id,
            "clone_name": self.clone_name,
            "workdir": self.workdir,
            "isolated_base_url": self.isolated_base_url,
            "bank_id": self.bank_id,
            "profile_id": self.profile_id,
            "is_memory_disabled": self.is_memory_disabled,
            "fixtures_dir": self.fixtures_dir,
            "source_env_checksum": self.source_env_checksum,
            "hermes_bin": self.hermes_bin,
            "cloned_files": list(self.cloned_files),
        }


def compute_profile_checksum(profile_path: str) -> str:
    """Compute SHA-256 checksum of a profile's .env file (first 16 hex chars).

    Returns "" if the profile has no .env. Used as the read-only source
    identity fingerprint before/after a clone cycle.
    """
    env_path = Path(profile_path) / ".env"
    if not env_path.exists():
        return ""
    content = env_path.read_bytes()
    return hashlib.sha256(content).hexdigest()[:16]


def copy_profile_without_logging(source: str, target: str) -> bool:
    """Copy a profile's .env to target without logging its contents.

    Returns True if the file was copied, False if the source had no .env.
    """
    src_env = Path(source) / ".env"
    if not src_env.exists():
        return False
    dst_env = Path(target) / ".env"
    # Copy bytes directly — never read into a variable that could be logged.
    with open(src_env, "rb") as fs, open(dst_env, "wb") as fd:
        shutil.copyfileobj(fs, fd)
    try:
        os.chmod(dst_env, 0o600)
    except OSError:
        pass
    return True


def find_hermes_bin() -> Optional[str]:
    """Locate the hermes CLI executable.

    Order: PATH, then known install locations. Returns absolute path or None.
    """
    which = shutil.which("hermes")
    if which:
        return which
    candidates = [
        os.path.expanduser("~/.hermes/hermes-agent/.hermes/bin/hermes"),
        os.path.expanduser("~/.hermes/hermes-agent/bin/hermes"),
        os.path.expanduser("~/.hermes/bin/hermes"),
    ]
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def _profiles_home() -> Path:
    """Directory that contains per-profile subdirs (e.g. ~/.hermes/profiles).

    HERMES_HOME may be (a) the profiles home itself (…/profiles), (b) a specific
    profile dir (…/profiles/<name>), or (c) a bare home dir (…/.hermes). Resolve
    the actual profiles home in all three cases; default to ~/.hermes/profiles.
    """
    default = Path(os.path.expanduser("~/.hermes")) / "profiles"
    env = os.environ.get("HERMES_HOME")
    if env:
        p = Path(env)
        if p.name == "profiles":          # HERMES_HOME is the profiles home itself
            return p
        if p.parent.name == "profiles":   # HERMES_HOME is one profile dir (…/profiles/<name>)
            return p.parent
        cand = p / "profiles"             # HERMES_HOME is a bare home dir (…/.hermes)
        if cand.is_dir():
            return cand
    if default.is_dir():
        return default
    if env:
        return Path(env) / "profiles"
    return default


def isolate_test_profile(
    source_profile: str = "bubo",
    workdir: Optional[str] = None,
    suffix: str = "_test",
) -> ProfileIsolationContext:
    """Create an isolated, fully functional Hermes test profile by cloning the source.

    The clone is a real profile directory (config.yaml + .env + identity + skills)
    under <profiles_home>/<clone_id>, so the Hermes CLI can resolve it. The source
    profile is treated as read-only: we only read from it, and we snapshot its
    .env checksum before and after to prove it was not modified.

    Args:
        source_profile: Name of the source profile (e.g. "bubo")
        workdir: Optional override for the clone directory (defaults to
            <profiles_home>/<clone_id>)
        suffix: Name prefix for the clone id
    """
    profiles_home = _profiles_home()
    profiles_home.mkdir(parents=True, exist_ok=True)
    src = profiles_home / source_profile

    if not src.is_dir():
        raise FileNotFoundError(f"Source profile not found: {src}")

    clone_id = f"{source_profile}{suffix}_{uuid.uuid4().hex[:8]}"
    clone_dir = Path(workdir) if workdir else profiles_home / clone_id
    if clone_dir.exists():
        shutil.rmtree(clone_dir)
    clone_dir.mkdir(parents=True, exist_ok=True)

    # Snapshot source .env checksum BEFORE any copy (read-only proof).
    source_env_checksum = compute_profile_checksum(str(src))

    # Copy the functional file/dir set (never the heavy regenerable state).
    cloned_files: List[str] = []
    for name in CLONE_FILES:
        s = src / name
        if s.exists():
            shutil.copy2(s, clone_dir / name)
            cloned_files.append(name)
    for name in CLONE_DIRS:
        s = src / name
        if s.is_dir():
            shutil.copytree(s, clone_dir / name, symlinks=True)
            cloned_files.append(f"{name}/")

    # .env must be present if the source had one — a functional clone needs it.
    if (src / ".env").exists() and not (clone_dir / ".env").exists():
        raise RuntimeError(f"Failed to copy .env into clone {clone_dir}")
    # config.yaml is what lets the CLI resolve the model — fail loudly if missing.
    if not (clone_dir / "config.yaml").exists():
        raise RuntimeError(
            f"Clone {clone_dir} lacks config.yaml; CLI cannot resolve the model."
        )

    # Per-profile fixture workspace + sessions dir.
    fixtures_dir = str(clone_dir / "fixtures")
    Path(fixtures_dir).mkdir(parents=True, exist_ok=True)
    (clone_dir / "sessions").mkdir(parents=True, exist_ok=True)

    bank_id = uuid.uuid4().hex[:8]
    profile_id = f"{bank_id}_{clone_id}"
    hermes_bin = find_hermes_bin()

    return ProfileIsolationContext(
        source_profile=source_profile,
        clone_id=clone_id,
        workdir=str(clone_dir),
        clone_dir=str(clone_dir),
        clone_name=clone_id,
        isolated_base_url=None,
        bank_id=bank_id,
        profile_id=profile_id,
        is_memory_disabled=True,
        fixtures_dir=fixtures_dir,
        source_env_checksum=source_env_checksum,
        hermes_bin=hermes_bin,
        cloned_files=cloned_files,
        hermes_home=str(profiles_home),
    )


def read_profile_model(profile_dir) -> tuple[str, str]:
    """Read (model, provider) from a profile's config.yaml (model.default / model.provider).

    Returns ("", "") if the file is absent or unparseable. Used to populate the
    client's .model/.provider attributes so reports are accurate in hermes mode.
    """
    import yaml
    cfg_path = Path(profile_dir) / "config.yaml"
    if not cfg_path.exists():
        return ("", "")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        return ("", "")
    model = (cfg.get("model") or {}).get("default", "") if isinstance(cfg.get("model"), dict) else ""
    provider = (cfg.get("model") or {}).get("provider", "") if isinstance(cfg.get("model"), dict) else ""
    return (str(model) if model else "", str(provider) if provider else "")


def verify_source_unchanged(profile_ctx: ProfileIsolationContext) -> bool:
    """Re-checksum the source profile .env and compare against the pre-clone snapshot.

    Returns True if the source is unchanged (or had no .env to begin with).
    """
    profiles_home = _profiles_home()
    src = profiles_home / profile_ctx.source_profile
    if not src.is_dir():
        return False
    now = compute_profile_checksum(str(src))
    if not profile_ctx.source_env_checksum:
        return not (src / ".env").exists()
    return now == profile_ctx.source_env_checksum


def cleanup_profile_clone(profile_ctx: ProfileIsolationContext, confirm: bool = True) -> bool:
    """Remove the cloned test profile directory (and only that directory).

    Safety: never deletes the source profile or the profiles parent. Returns
    True if the clone is gone (or was already gone), False otherwise.
    """
    clone_dir = Path(profile_ctx.workdir or profile_ctx.clone_dir or "")
    if not str(clone_dir):
        return True
    if not clone_dir.exists():
        return True
    # Guard: never delete the source profile or the profiles parent.
    profiles_home = Path(profile_ctx.hermes_home or _profiles_home())
    src = profiles_home / profile_ctx.source_profile
    try:
        resolved = clone_dir.resolve()
        if resolved == src.resolve() or resolved == profiles_home.resolve():
            print("[hermes] Refusing to delete source/profiles-home dir", file=sys.stderr)
            return False
    except Exception:
        pass
    if not confirm:
        return True
    shutil.rmtree(clone_dir, ignore_errors=True)
    return not clone_dir.exists()


def verify_session_isolation(profile_ctx: ProfileIsolationContext) -> bool:
    """Verify that the test profile has its own session dir and isolated identity."""
    clone_dir = Path(profile_ctx.workdir or profile_ctx.clone_dir or "")
    if not clone_dir or not clone_dir.exists():
        return False
    if not profile_ctx.clone_name or not profile_ctx.clone_name:
        return False
    if profile_ctx.is_memory_disabled:
        return (clone_dir / "fixtures").exists()
    return (clone_dir / "fixtures").exists() and (clone_dir / "memories").exists()


def create_fixture_workspace(profile_ctx: ProfileIsolationContext, name: str = "fixtures") -> str:
    """Create and return a per-profile fixture workspace directory."""
    if not profile_ctx.fixtures_dir:
        base = Path(profile_ctx.workdir or profile_ctx.clone_dir or ".")
        fixtures_dir = str(base / name)
    else:
        fixtures_dir = profile_ctx.fixtures_dir
    Path(fixtures_dir).mkdir(parents=True, exist_ok=True)
    return fixtures_dir


def disable_memory_for_test_profile(profile_ctx: ProfileIsolationContext) -> None:
    """Mark the test profile as memory-disabled (no bank writes)."""
    profile_ctx.is_memory_disabled = True


def setup_isolated_profile(
    source_profile: str = "bubo",
    workdir: Optional[str] = None,
) -> ProfileIsolationContext:
    """Backwards-compatible alias for isolate_test_profile."""
    ctx = isolate_test_profile(source_profile=source_profile, workdir=workdir)
    disable_memory_for_test_profile(ctx)
    create_fixture_workspace(ctx)
    return ctx


def cleanup_isolated_profile(profile_ctx: ProfileIsolationContext) -> bool:
    """Backwards-compatible alias for cleanup_profile_clone."""
    return cleanup_profile_clone(profile_ctx, confirm=True)
