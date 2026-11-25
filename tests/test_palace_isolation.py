#!/usr/bin/env python3
"""MemChorus palace isolation: per-profile recall-store separation.

Incident history (task t_908c7b2e): on 2026-11-25, glaqux's memchorus config
pointed at bubо's palace leaf (84 chroma rows + their pointer files), so
glaux's injected context block contained bubо's items as if they were its
own. t_7e82ff0c reset glaqux to its own empty leaf and confirmed all 6 live
profiles now own physically distinct leaves. This suite keeps that invariant
as a *failing test* instead of a production incident.

Invariants under test:
  1. A profile's injected context block (full ``on_pre_llm_call`` pipeline)
     contains ONLY items whose key resolves in that profile's own store leaf.
     No item may carry a source/ownership pointing at another profile.
  2. A shared drawer item (same key present in a foreign leaf) is reachable by
     explicit ID in the owning profile, and is never auto-injected into a
     profile that does not own the key.
  3. ``memchorus-recall retrieve`` (``run_retrieve``) validates pointer
     ownership before returning: resolution runs against the READER's own
     leaf only — a foreign key is a clean miss (exit 1), never a foreign hit.
  4. Edge cases: empty drawer, broken ref (pointer key absent from the reader
     leaf), shared artifact (same key, distinct bodies, both owners).

Hermeticity: profiles are synthetic (``alpha``/``beta``/``gamma``) with fresh
``tmp_path`` store leaves; no live palace, no Chroma, no MCP, no credentials.
The in-process orchestrator registry (``memchorus._INSTANCE_REGISTRY``) is
cleaned up after every test.
"""

import os
import re
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import memchorus
from memchorus import MemoryOrchestrator
from memchorus.hooks import MemChorusHooks
from memchorus.recall_cli import run_retrieve


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _Profile:
    """A synthetic profile: name + store leaf + hermes-only orchestrator."""

    __slots__ = ("name", "leaf", "orch")

    def __init__(self, name, leaf, orch):
        self.name = name
        self.leaf = leaf
        self.orch = orch


def _make_profile(root, name):
    """Build one synthetic profile whose store leaf is physically isolated."""
    leaf = os.path.join(str(root), "profiles", name, "memories")
    os.makedirs(leaf, exist_ok=True)
    config = {
        "default_source": "hermes_default",
        "hermes_default_config": {"memory_dir": leaf},
        "mempalace_config": {"skip_mcp": True},
    }
    orch = MemoryOrchestrator(config)
    # Recall isolation is about the hermes memory store; drop any other
    # sources so the leaf is the ONLY place an item can resolve.
    for src_name in list(orch.memory_sources):
        if src_name != "hermes_default":
            orch.unregister_source(src_name)
    return _Profile(name, leaf, orch)


def _injected_keys(context):
    """Extract the bold key of every ``- **key** — ...`` entry in a block."""
    if not context:
        return []
    return re.findall(r"-\s+\*\*([A-Za-z0-9_\-]+)\*\*", context)


def _inject(profile, user_text):
    """Run the FULL pre-LLM-call injection pipeline for one profile.

    ``_get_orchestrator`` is patched so the pipeline resolves exactly this
    profile's orchestrator — the same seam the live hook uses per profile.
    """
    hooks = memchorus.hooks
    with mock.patch.object(hooks, "_get_orchestrator", return_value=profile.orch):
        return MemChorusHooks().on_pre_llm_call(
            user_message=user_text,
            conversation_history=[],
            session_id=f"palace-test-{profile.name}",
            task_id="",
        )


@pytest.fixture
def palaces(tmp_path):
    """Two synthetic profiles on distinct leaves, seeded with disjoint items.

    alpha owns ``vault-decision`` and ``alpha-note``; beta owns
    ``beta-only-note``. ``gamma`` (empty drawer) is available too.
    Yields the tuple and tears down any registry entries.
    """
    profiles = [_make_profile(tmp_path, name) for name in ("alpha", "beta", "gamma")]
    by = {p.name: p for p in profiles}

    by["alpha"].orch.save("vault-decision",
                          "Decision: vault code is 7384-ALPHA. Settled 2026-11-20.")
    by["alpha"].orch.save("alpha-note",
                          "Alpha only: the relay rotation order for the vault.")
    by["beta"].orch.save("beta-only-note",
                         "Beta only: tailnet roster and vault code 7384-BETA.")

    yield tuple(profiles)

    # Clean the in-process registry so no later test inherits an orchestrator.
    for p in profiles:
        memchorus._INSTANCE_REGISTRY.pop(p.name, None)


@pytest.fixture
def alpha_beta(palaces):
    by = {p.name: p for p in palaces}
    return by["alpha"], by["beta"]


# ---------------------------------------------------------------------------
# Structural: distinct store leaves (the glaqux failure mode)
# ---------------------------------------------------------------------------

class TestLeafSeparation:
    def test_profiles_have_distinct_store_leaves(self, alpha_beta):
        alpha, beta = alpha_beta
        assert os.path.isdir(alpha.leaf)
        assert os.path.isdir(beta.leaf)
        # The incident was a config pointing two profiles at ONE leaf.
        assert os.path.realpath(alpha.leaf) != os.path.realpath(beta.leaf)

    def test_leaf_collision_detection_flags_shared_leaf(self, alpha_beta):
        alpha, beta = alpha_beta

        def collisions(leaves):
            seen = {}
            for leaf in leaves:
                real = os.path.realpath(leaf)
                seen.setdefault(real, []).append(leaf)
            return [paths for paths in seen.values() if len(paths) > 1]

        # Happy path: the suite's own profiles are clean.
        assert collisions([alpha.leaf, beta.leaf]) == []
        # Simulated misconfiguration (the glaqux bug): both profiles point at
        # alpha's leaf — the detector must flag it.
        assert collisions([alpha.leaf, alpha.leaf]) == [[alpha.leaf, alpha.leaf]]


# ---------------------------------------------------------------------------
# Requirement 1 + 3: injected block contains only the reader's own items
# ---------------------------------------------------------------------------

class TestInjectionScope:
    def test_alpha_block_contains_only_own_keys(self, alpha_beta):
        alpha, beta = alpha_beta
        result = _inject(alpha, "what was the vault code decision?")
        assert result is not None, "alpha should inject its own items"
        ctx = result["context"]
        assert "vault-decision" in ctx, "alpha's own key must be injected"
        assert "beta-only-note" not in ctx, (
            "beta's key leaked into alpha's injected block (cross-profile)"
        )
        # Ownership of EVERY injected key: resolves in alpha's leaf,
        # and no foreign leaf holds the same key.
        for key in _injected_keys(ctx):
            assert alpha.orch.retrieve(key) is not None, (
                f"injected key {key!r} does not resolve in alpha's own leaf"
            )
            assert beta.orch.retrieve(key) is None, (
                f"injected key {key!r} is owned by beta's leaf — foreign item"
            )

    def test_beta_block_contains_only_own_keys(self, alpha_beta):
        alpha, beta = alpha_beta
        result = _inject(beta, "what was the vault code decision?")
        assert result is not None, "beta should inject its own items"
        ctx = result["context"]
        assert "beta-only-note" in ctx, "beta's own key must be injected"
        assert "vault-decision" not in ctx, (
            "alpha's key leaked into beta's injected block (cross-profile)"
        )
        assert "alpha-note" not in ctx, (
            "alpha's key leaked into beta's injected block (cross-profile)"
        )
        for key in _injected_keys(ctx):
            assert beta.orch.retrieve(key) is not None, (
                f"injected key {key!r} does not resolve in beta's own leaf"
            )
            assert alpha.orch.retrieve(key) is None, (
                f"injected key {key!r} is owned by alpha's leaf — foreign item"
            )

    def test_injected_key_absent_from_foreign_leaf(self, alpha_beta):
        """Requirement 3 (assertion form): no injected item's key may be
        retrievable from another profile's leaf."""
        alpha, beta = alpha_beta
        ra = _inject(alpha, "vault code decision relay rotation")
        rb = _inject(beta, "vault code decision tailnet roster")
        for result, own, foreign in ((ra, alpha, beta), (rb, beta, alpha)):
            if not result:
                continue
            for key in _injected_keys(result["context"]):
                assert own.orch.retrieve(key) is not None
                assert foreign.orch.retrieve(key) is None, (
                    f"key {key!r} in {own.name}'s block also resolves in "
                    f"{foreign.name}'s leaf — cross-profile source"
                )


# ---------------------------------------------------------------------------
# Requirement 2: shared items — explicit ID works, auto-injection does not
# ---------------------------------------------------------------------------

class TestSharedItemAccess:
    def test_foreign_key_reachable_by_owner_via_explicit_id(self, alpha_beta, capsys):
        alpha, beta = alpha_beta
        memchorus.register_orchestrator(alpha.orch, "alpha")
        memchorus.register_orchestrator(beta.orch, "beta")
        try:
            rc = run_retrieve("vault-decision", as_json=False, profile="alpha")
            out = capsys.readouterr().out
            assert rc == 0, f"owner's explicit retrieve should hit (rc={rc})"
            assert "7384-ALPHA" in out, "owner's copy must come back verbatim"
        finally:
            memchorus._INSTANCE_REGISTRY.pop("alpha", None)
            memchorus._INSTANCE_REGISTRY.pop("beta", None)

    def test_foreign_key_not_auto_injected_into_non_owner(self, alpha_beta):
        alpha, beta = alpha_beta
        # alpha's item is live and query-matching — but beta must not show it.
        result = _inject(beta, "what was the vault code decision?")
        ctx = result["context"] if result else ""
        assert "vault-decision" not in ctx, (
            "alpha's item was auto-injected into beta's block"
        )
        assert "7384-ALPHA" not in ctx

    def test_shared_artifact_each_reader_gets_own_copy(self, alpha_beta, capsys):
        """Same key in BOTH leaves (a shared artifact): each profile may inject
        it — it is its OWN copy — and explicit retrieval returns the reader's
        copy, never the other profile's body."""
        alpha, beta = alpha_beta
        alpha.orch.save("shared-artifact",
                        "Shared artifact — ALPHA copy: checksum sha256:aaaa1111")
        beta.orch.save("shared-artifact",
                       "Shared artifact — BETA copy: checksum sha256:bbbb2222")

        ra = _inject(alpha, "shared artifact checksum")
        rb = _inject(beta, "shared artifact checksum")
        assert ra and "shared-artifact" in ra["context"], (
            "alpha owns this key — its block should include its own copy"
        )
        assert rb and "shared-artifact" in rb["context"], (
            "beta owns this key — its block should include its own copy"
        )

        memchorus.register_orchestrator(alpha.orch, "alpha")
        memchorus.register_orchestrator(beta.orch, "beta")
        try:
            rc_a = run_retrieve("shared-artifact", as_json=False, profile="alpha")
            out_a = capsys.readouterr().out
            rc_b = run_retrieve("shared-artifact", as_json=False, profile="beta")
            out_b = capsys.readouterr().out
            assert rc_a == 0 and "aaaa1111" in out_a, "alpha must get its copy"
            assert rc_b == 0 and "bbbb2222" in out_b, "beta must get its copy"
            assert "bbbb2222" not in out_a, (
                "alpha's retrieve returned beta's copy (cross-profile body)"
            )
            assert "aaaa1111" not in out_b, (
                "beta's retrieve returned alpha's copy (cross-profile body)"
            )
        finally:
            memchorus._INSTANCE_REGISTRY.pop("alpha", None)
            memchorus._INSTANCE_REGISTRY.pop("beta", None)


# ---------------------------------------------------------------------------
# Requirement 3: retrieve validates pointer ownership (reader's leaf only)
# ---------------------------------------------------------------------------

class TestPointerOwnership:
    def test_run_retrieve_hit_in_own_leaf_exit0(self, alpha_beta, capsys):
        alpha, _beta = alpha_beta
        memchorus.register_orchestrator(alpha.orch, "alpha")
        try:
            rc = run_retrieve("alpha-note", as_json=False, profile="alpha")
            out = capsys.readouterr().out
            assert rc == 0
            assert "relay rotation" in out
        finally:
            memchorus._INSTANCE_REGISTRY.pop("alpha", None)

    def test_run_retrieve_foreign_key_is_miss_not_foreign_hit(self, alpha_beta, capsys):
        alpha, beta = alpha_beta
        memchorus.register_orchestrator(alpha.orch, "alpha")
        memchorus.register_orchestrator(beta.orch, "beta")
        try:
            # beta does NOT own alpha-note: clean miss (exit 1), never a hit
            # that happens to read alpha's leaf.
            rc = run_retrieve("alpha-note", as_json=False, profile="beta")
            out = capsys.readouterr().out
            assert rc == 1, (
                f"foreign key should be a miss (exit 1), got rc={rc}"
            )
            assert "relay rotation" not in out, (
                "beta's miss printed alpha's body — foreign hit"
            )
        finally:
            memchorus._INSTANCE_REGISTRY.pop("alpha", None)
            memchorus._INSTANCE_REGISTRY.pop("beta", None)

    def test_run_retrieve_unreachable_pipeline_exit2(self, alpha_beta, capsys):
        """Pipeline unreachable (orchestrator without callable `retrieve`) must
        exit 2 with an error — never a silent cross-profile fallback hit."""
        _alpha, _beta = alpha_beta

        class _BrokenOrch:
            retrieve = None  # not callable → pipeline unreachable (spec-253 D1)

        memchorus.register_orchestrator(_BrokenOrch(), "broken")
        try:
            rc = run_retrieve("vault-decision", as_json=False, profile="broken")
            err = capsys.readouterr().err
            assert rc == 2, f"unreachable pipeline should exit 2, got {rc}"
            assert "error" in err.lower()
        finally:
            memchorus._INSTANCE_REGISTRY.pop("broken", None)

    def test_probe_classifies_own_resolved_foreign_dead(self, alpha_beta):
        """C13 liveness: a key is RESOLVED only inside the reader's own leaf;
        a foreign key is a clean DEAD (clean miss), not a cross-profile hit."""
        alpha, beta = alpha_beta
        assert alpha.orch.probe_recall_key_liveness("vault-decision") == "RESOLVED"
        assert alpha.orch.probe_recall_key_liveness("beta-only-note") == "DEAD"
        assert beta.orch.probe_recall_key_liveness("vault-decision") == "DEAD"
        assert beta.orch.probe_recall_key_liveness("beta-only-note") == "RESOLVED"


# ---------------------------------------------------------------------------
# Requirement 4: edge cases — empty drawer, broken ref, (shared artifact above)
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_drawer_injects_nothing_foreign(self, palaces):
        by = {p.name: p for p in palaces}
        gamma = by["gamma"]  # empty store leaf, alpha's items are query-matching
        result = _inject(gamma, "what was the vault code decision?")
        ctx = result["context"] if result else ""
        assert "vault-decision" not in ctx, (
            "empty-drawer profile injected alpha's item"
        )
        assert "beta-only-note" not in ctx
        assert "alpha-note" not in ctx
        # And an empty drawer must not fabricate its own items either.
        for key in _injected_keys(ctx):
            assert gamma.orch.retrieve(key) is not None, (
                f"empty-drawer profile injected key {key!r} it does not own"
            )

    def test_broken_ref_dropped_before_injection(self, alpha_beta):
        """Broken ref: a pointer whose key no longer resolves in the reader's
        leaf must be dropped by the liveness gate (with a diagnostic), not
        injected as if live."""
        alpha, _beta = alpha_beta
        broken = {
            "key": "ghost-note",
            "content": (
                "**ghost-note** — source=hermes_default— read it: "
                "`memchorus-recall retrieve ghost-note`. Ghost gist."
            ),
        }
        kept = alpha.orch.apply_recall_liveness([dict(broken)])
        assert kept == [], (
            f"broken-ref pointer survived the liveness gate: {kept!r}"
        )
        diags = alpha.orch.get_c13_diagnostics()
        assert any("ghost-note" in d and "DEAD" in d for d in diags), (
            f"expected a DEAD diagnostic for ghost-note, got {diags!r}"
        )

    def test_live_pointer_kept_by_gate(self, alpha_beta):
        """Positive control: a pointer whose key resolves in the reader's leaf
        passes the gate unchanged (RESOLVED)."""
        alpha, _beta = alpha_beta
        item = {
            "key": "vault-decision",
            "content": (
                "**vault-decision** — source=hermes_default— read it: "
                "`memchorus-recall retrieve vault-decision`."
            ),
        }
        kept = alpha.orch.apply_recall_liveness([dict(item)])
        assert len(kept) == 1, f"live pointer was dropped: {kept!r}"
        assert kept[0]["key"] == "vault-decision"
        assert kept[0].get("_c13_liveness") in ("RESOLVED", "COLD", "UNKNOWN")

    def test_broken_ref_not_injected_full_pipeline(self, alpha_beta):
        """Full pipeline: a pointer item removed from alpha's leaf must vanish
        from alpha's injected block (whether search prunes it or the liveness
        gate drops it — either way, no phantom injection)."""
        alpha, _beta = alpha_beta
        # Control: the item IS injected while it is live.
        ra_before = _inject(alpha, "vault code decision relay rotation")
        ctx_before = ra_before["context"] if ra_before else ""
        assert "vault-decision" in ctx_before, (
            "control failed — live item not injected before deletion"
        )

        # Remove the body from alpha's leaf (broken ref).
        if hasattr(alpha.orch, "delete"):
            alpha.orch.delete("vault-decision")
        else:  # fall back to deleting the store file(s) directly
            for fn in os.listdir(alpha.leaf):
                if "vault-decision" in fn:
                    os.remove(os.path.join(alpha.leaf, fn))
        alpha.orch.clear_cache()

        ra_after = _inject(alpha, "vault code decision relay rotation")
        ctx_after = ra_after["context"] if ra_after else ""
        assert "vault-decision" not in ctx_after, (
            "broken-ref pointer was injected although its body is gone"
        )