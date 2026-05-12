"""
Tests for inline token monitoring in AtmanRunner.chat() loop.

These tests verify E22.3 implementation by calling the extracted
_check_token_usage() method directly. This ensures tests exercise
production code paths rather than reimplementing logic.

Tests verify:
- Progressive warnings at 70%, 80%, 90% thresholds
- Forced session close at 95%
- Multiple thresholds fire in single call (not 'elif' chain)
- Stateful trigger tracking prevents duplicate warnings
- Triggers reset on session restart
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from atman.adapters.agent.config import AgentConfig, ModelConfig
from atman.adapters.agent.runner import AtmanRunner
from atman.adapters.storage.file_state_store import FileStateStore
from atman.core.models import Identity, LayerType, NarrativeDocument, NarrativeLayer


@pytest.fixture
def identity_with_narrative(tmp_path: Path) -> Identity:
    """Create test identity with narrative."""
    store = FileStateStore(workspace=tmp_path)
    agent_id = uuid4()

    identity = Identity(
        id=agent_id,
        self_description="Test Agent",
    )
    store.save_identity(identity)

    narrative = NarrativeDocument(
        id=uuid4(),
        identity_id=agent_id,
        core_layer=NarrativeLayer(content="Core identity", layer_type=LayerType.CORE),
        recent_layer=NarrativeLayer(content="Recent experiences", layer_type=LayerType.RECENT),
    )
    store.save_narrative(narrative)

    return identity


def test_runner_token_monitoring_multi_threshold_jump(
    tmp_path: Path, identity_with_narrative: Identity
) -> None:
    """
    Test that multiple thresholds fire when usage jumps across boundaries.

    Regression test for BUG-0001: ensures independent 'if' (not 'elif') so all
    crossed thresholds trigger in same call. When usage jumps from 65% to 92%,
    all three thresholds (70%, 80%, 90%) should fire.
    """
    config = AgentConfig(
        model=ModelConfig(context_limit=1000),
    )
    runner = AtmanRunner(tmp_path, identity_with_narrative.id, config)

    # Simulate usage at 92% (920/1000) — crosses 70%, 80%, 90%
    newly_triggered, should_force_close = runner._check_token_usage(
        input_tokens=920, context_limit=1000
    )

    # All three thresholds should fire in single call
    assert newly_triggered == {70, 80, 90}, "All crossed thresholds should fire"
    assert should_force_close is False, "95% not reached, should not force close"
    assert runner._triggered == {70, 80, 90}, "All triggers should be recorded"


def test_runner_token_monitoring_no_duplicate_warnings(
    tmp_path: Path, identity_with_narrative: Identity
) -> None:
    """
    Test that each threshold fires only once across multiple calls.

    Verifies that self._triggered set prevents duplicate warnings when usage
    stays above a threshold across multiple _check_token_usage() calls.
    """
    config = AgentConfig(
        model=ModelConfig(context_limit=1000),
    )
    runner = AtmanRunner(tmp_path, identity_with_narrative.id, config)

    # First call: usage at 75% (crosses 70%)
    newly_triggered_1, should_force_close_1 = runner._check_token_usage(
        input_tokens=750, context_limit=1000
    )
    assert newly_triggered_1 == {70}, "70% should fire on first call"
    assert should_force_close_1 is False
    assert runner._triggered == {70}

    # Second call: usage still at 75% (no new thresholds)
    newly_triggered_2, should_force_close_2 = runner._check_token_usage(
        input_tokens=750, context_limit=1000
    )
    assert newly_triggered_2 == set(), "No new thresholds on second call"
    assert should_force_close_2 is False
    assert runner._triggered == {70}, "Still only 70 triggered (no duplicates)"


def test_runner_token_monitoring_reset_on_restart(
    tmp_path: Path, identity_with_narrative: Identity
) -> None:
    """
    Test that _triggered set can be cleared (done during restart).

    Verifies that thresholds can fire again after _triggered.clear() in _do_restart().
    """
    config = AgentConfig(
        model=ModelConfig(context_limit=1000),
    )
    runner = AtmanRunner(tmp_path, identity_with_narrative.id, config)

    # Trigger 70%
    newly_triggered_1, _ = runner._check_token_usage(input_tokens=720, context_limit=1000)
    assert newly_triggered_1 == {70}
    assert runner._triggered == {70}

    # Simulate restart: clear triggers (done in _do_restart)
    runner._triggered.clear()
    assert runner._triggered == set()

    # After restart, 70% can fire again
    newly_triggered_2, _ = runner._check_token_usage(input_tokens=720, context_limit=1000)
    assert newly_triggered_2 == {70}, "70% fires again after restart"
    assert runner._triggered == {70}


def test_runner_token_monitoring_95_threshold_fires_with_lower(
    tmp_path: Path, identity_with_narrative: Identity
) -> None:
    """
    Test that 95% threshold + force-close coexists with lower thresholds.

    When usage jumps to 95%, all lower thresholds (70/80/90) should still fire
    in the same call, and should_force_close returns True.
    """
    config = AgentConfig(
        model=ModelConfig(context_limit=1000),
    )
    runner = AtmanRunner(tmp_path, identity_with_narrative.id, config)

    # Simulate usage at 95% (950/1000) — crosses all thresholds
    newly_triggered, should_force_close = runner._check_token_usage(
        input_tokens=950, context_limit=1000
    )

    # All four thresholds should fire in single call
    assert newly_triggered == {70, 80, 90, 95}, "All thresholds including 95% should fire"
    assert should_force_close is True, "95% should trigger force-close"
    assert runner._triggered == {70, 80, 90, 95}, "All triggers recorded"


def test_runner_token_monitoring_95_only_when_above_threshold(
    tmp_path: Path, identity_with_narrative: Identity
) -> None:
    """
    Test that 95% threshold only fires when usage is actually >=95%.

    Verifies boundary condition: 94.9% should not trigger force-close.
    """
    config = AgentConfig(
        model=ModelConfig(context_limit=1000),
    )
    runner = AtmanRunner(tmp_path, identity_with_narrative.id, config)

    # Usage at 94.9% (949/1000) — just below 95%
    newly_triggered, should_force_close = runner._check_token_usage(
        input_tokens=949, context_limit=1000
    )

    assert 95 not in newly_triggered, "95% should not fire at 94.9%"
    assert should_force_close is False, "Should not force close at 94.9%"
    assert 70 in newly_triggered and 80 in newly_triggered and 90 in newly_triggered
    assert runner._triggered == {70, 80, 90}, "Only 70/80/90 triggered"
