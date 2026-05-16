"""
Tests for the self-apply API on IdentityService and NarrativeRevisionService,
plus the InMemorySelfAppliedChangeStore adapter.

Self-applied changes are reflection's path to modifying identity/narrative
without an explicit human GovernanceDecision. Each change must carry rationale
and supporting moments (enforced at model construction) and produce an
auditable record that can be reverted.
"""

from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import pytest

from atman.adapters.storage import FileStateStore
from atman.adapters.storage.in_memory_self_applied_changes import (
    InMemorySelfAppliedChangeStore,
)
from atman.core.models import (
    CoreValue,
    OpenQuestion,
    Principle,
    SelfAppliedChange,
    SelfChangeActor,
    SelfChangeSource,
    SelfChangeTargetKind,
)
from atman.core.models.narrative import LayerType, NarrativeDocument, NarrativeLayer
from atman.core.narrative_write_audit import NoOpNarrativeWriteAudit
from atman.core.services import IdentityService
from atman.core.services.narrative_revision import NarrativeRevisionService

# ---------------------------------------------------------------------------
# Source model invariants
# ---------------------------------------------------------------------------


def test_source_requires_rationale_and_confidence():
    with pytest.raises(ValueError):
        SelfChangeSource(
            actor=SelfChangeActor.REFLECTION_DAILY,
            reflection_event_id=uuid4(),
            rationale="   ",
            confidence_self_assessment="something",
            based_on_moment_ids=[],
        )
    with pytest.raises(ValueError):
        SelfChangeSource(
            actor=SelfChangeActor.REFLECTION_DAILY,
            reflection_event_id=uuid4(),
            rationale="ok",
            confidence_self_assessment="",
            based_on_moment_ids=[],
        )


# ---------------------------------------------------------------------------
# InMemorySelfAppliedChangeStore contract
# ---------------------------------------------------------------------------


def _make_change(**overrides) -> SelfAppliedChange:
    defaults = dict(
        actor=SelfChangeActor.REFLECTION_DAILY,
        reflection_event_id=uuid4(),
        target_kind=SelfChangeTargetKind.IDENTITY_PRINCIPLE,
        target_ref="principle:test",
        before_snapshot={"principles": []},
        after_snapshot={"principles": [{"statement": "x"}]},
        rationale="reason",
        confidence_self_assessment="why I think this is right",
        based_on_moment_ids=[],
    )
    defaults.update(overrides)
    return SelfAppliedChange(**defaults)


def test_store_save_and_get():
    store = InMemorySelfAppliedChangeStore()
    change = _make_change()
    store.save(change)
    assert store.get(change.id) == change


def test_store_rejects_duplicate_save():
    store = InMemorySelfAppliedChangeStore()
    change = _make_change()
    store.save(change)
    with pytest.raises(ValueError):
        store.save(change)


def test_store_list_filters_and_orders_newest_first():
    store = InMemorySelfAppliedChangeStore()
    older = _make_change(actor=SelfChangeActor.REFLECTION_DAILY)
    newer = _make_change(actor=SelfChangeActor.REFLECTION_DEEP)
    store.save(older)
    # ensure ordering not dependent on insertion order — bump applied_at
    newer = newer.model_copy(update={"applied_at": datetime(2030, 1, 1, tzinfo=older.applied_at.tzinfo)})
    store.save(newer)

    assert store.list() == [newer, older]
    assert store.list(actor=SelfChangeActor.REFLECTION_DEEP) == [newer]
    assert store.list(limit=1) == [newer]


def test_store_mark_reverted_is_one_shot():
    store = InMemorySelfAppliedChangeStore()
    change = _make_change()
    store.save(change)
    reverted = store.mark_reverted(
        change.id,
        reverted_at=datetime(2030, 1, 1, tzinfo=change.applied_at.tzinfo),
        reason="bad idea",
    )
    assert reverted.reverted_at is not None
    assert not reverted.is_active
    with pytest.raises(ValueError):
        store.mark_reverted(
            change.id,
            reverted_at=datetime(2030, 1, 2, tzinfo=change.applied_at.tzinfo),
            reason="again",
        )


def test_store_mark_reverted_unknown_id():
    store = InMemorySelfAppliedChangeStore()
    with pytest.raises(KeyError):
        store.mark_reverted(
            uuid4(),
            reverted_at=datetime(2030, 1, 1),
            reason="x",
        )


def test_store_only_active_filter():
    store = InMemorySelfAppliedChangeStore()
    a = _make_change()
    b = _make_change()
    store.save(a)
    store.save(b)
    store.mark_reverted(a.id, reverted_at=datetime.now(a.applied_at.tzinfo), reason="r")
    actives = store.list(only_active=True)
    assert b in actives
    assert a not in actives


# ---------------------------------------------------------------------------
# IdentityService.apply_self_change
# ---------------------------------------------------------------------------


def _identity_service(tmp: Path, *, with_audit: bool = True) -> tuple[IdentityService, InMemorySelfAppliedChangeStore]:
    audit = InMemorySelfAppliedChangeStore() if with_audit else None
    svc = IdentityService(FileStateStore(tmp), self_applied_change_store=audit)
    return svc, audit  # type: ignore[return-value]


def _make_source(actor: SelfChangeActor = SelfChangeActor.REFLECTION_DAILY) -> SelfChangeSource:
    return SelfChangeSource(
        actor=actor,
        reflection_event_id=uuid4(),
        rationale="because the pattern is clear",
        confidence_self_assessment="three moments converge on this",
        based_on_moment_ids=[uuid4(), uuid4()],
    )


def test_apply_self_change_requires_audit_store():
    with TemporaryDirectory() as d:
        svc, _ = _identity_service(Path(d), with_audit=False)
        agent = uuid4()
        svc.bootstrap_identity(agent)
        with pytest.raises(RuntimeError):
            svc.apply_self_change(
                agent,
                SelfChangeTargetKind.IDENTITY_PRINCIPLE,
                Principle(statement="be honest", chosen_consciously=True),
                _make_source(),
            )


def test_apply_self_change_appends_principle_and_records_audit():
    with TemporaryDirectory() as d:
        svc, store = _identity_service(Path(d))
        agent = uuid4()
        svc.bootstrap_identity(agent)

        principle = Principle(statement="be honest", chosen_consciously=True)
        record = svc.apply_self_change(
            agent,
            SelfChangeTargetKind.IDENTITY_PRINCIPLE,
            principle,
            _make_source(),
        )

        ident = svc.get_identity(agent)
        assert ident is not None
        assert any(p.statement == "be honest" for p in ident.principles)

        # audit row exists
        assert store.get(record.id) == record
        assert record.target_kind == SelfChangeTargetKind.IDENTITY_PRINCIPLE
        assert record.before_snapshot == {"principles": []}
        assert len(record.after_snapshot["principles"]) == 1
        assert record.is_active


def test_apply_self_change_self_description_records_before_and_after():
    with TemporaryDirectory() as d:
        svc, _ = _identity_service(Path(d))
        agent = uuid4()
        svc.bootstrap_identity(agent)
        original = svc.get_identity(agent).self_description  # type: ignore[union-attr]

        record = svc.apply_self_change(
            agent,
            SelfChangeTargetKind.IDENTITY_SELF_DESCRIPTION,
            "I am learning to act more deliberately.",
            _make_source(),
        )
        assert record.before_snapshot == {"self_description": original}
        assert record.after_snapshot == {
            "self_description": "I am learning to act more deliberately."
        }


def test_apply_self_change_rejects_wrong_payload_type():
    with TemporaryDirectory() as d:
        svc, _ = _identity_service(Path(d))
        agent = uuid4()
        svc.bootstrap_identity(agent)
        with pytest.raises(TypeError):
            svc.apply_self_change(
                agent,
                SelfChangeTargetKind.IDENTITY_PRINCIPLE,
                "this is a string, not a Principle",
                _make_source(),
            )
        with pytest.raises(TypeError):
            svc.apply_self_change(
                agent,
                SelfChangeTargetKind.IDENTITY_SELF_DESCRIPTION,
                CoreValue(name="honesty", description="not a string"),
                _make_source(),
            )


def test_apply_self_change_refuses_narrative_kind():
    with TemporaryDirectory() as d:
        svc, _ = _identity_service(Path(d))
        agent = uuid4()
        svc.bootstrap_identity(agent)
        with pytest.raises(ValueError):
            svc.apply_self_change(
                agent,
                SelfChangeTargetKind.NARRATIVE_CORE_LAYER,
                "some text",
                _make_source(),
            )


# ---------------------------------------------------------------------------
# IdentityService.revert_self_change
# ---------------------------------------------------------------------------


def test_revert_self_change_restores_list_field():
    with TemporaryDirectory() as d:
        svc, _ = _identity_service(Path(d))
        agent = uuid4()
        svc.bootstrap_identity(agent)
        record = svc.apply_self_change(
            agent,
            SelfChangeTargetKind.IDENTITY_OPEN_QUESTION,
            OpenQuestion(question="what comes next?"),
            _make_source(),
        )
        ident = svc.get_identity(agent)
        assert ident is not None
        added = [q for q in ident.open_questions if q.question == "what comes next?"]
        assert added

        svc.revert_self_change(agent, record.id, reason="changed my mind")

        ident_after = svc.get_identity(agent)
        assert ident_after is not None
        assert all(q.question != "what comes next?" for q in ident_after.open_questions)


def test_revert_self_change_restores_self_description():
    with TemporaryDirectory() as d:
        svc, _ = _identity_service(Path(d))
        agent = uuid4()
        svc.bootstrap_identity(agent)
        original = svc.get_identity(agent).self_description  # type: ignore[union-attr]

        record = svc.apply_self_change(
            agent,
            SelfChangeTargetKind.IDENTITY_SELF_DESCRIPTION,
            "new wording",
            _make_source(),
        )
        svc.revert_self_change(agent, record.id, reason="not ready")
        assert svc.get_identity(agent).self_description == original  # type: ignore[union-attr]


def test_revert_self_change_double_revert_fails():
    with TemporaryDirectory() as d:
        svc, _ = _identity_service(Path(d))
        agent = uuid4()
        svc.bootstrap_identity(agent)
        record = svc.apply_self_change(
            agent,
            SelfChangeTargetKind.IDENTITY_SELF_DESCRIPTION,
            "x",
            _make_source(),
        )
        svc.revert_self_change(agent, record.id, reason="r1")
        with pytest.raises(ValueError):
            svc.revert_self_change(agent, record.id, reason="r2")


def test_revert_self_change_unknown_id():
    with TemporaryDirectory() as d:
        svc, _ = _identity_service(Path(d))
        agent = uuid4()
        svc.bootstrap_identity(agent)
        with pytest.raises(KeyError):
            svc.revert_self_change(agent, uuid4(), reason="x")


# ---------------------------------------------------------------------------
# NarrativeRevisionService self-apply
# ---------------------------------------------------------------------------


class _StubNarrativeRepo:
    def __init__(self, doc: NarrativeDocument) -> None:
        self._doc = doc

    def get_current(self) -> NarrativeDocument | None:
        return self._doc

    def update(self, draft: NarrativeDocument, expected_updated_at) -> None:
        # optimistic concurrency check (mirrors real adapters)
        if expected_updated_at != self._doc.updated_at:
            raise RuntimeError("etag mismatch")
        self._doc = draft


class _NullReflectionModel:
    """No methods needed for self-apply path."""


def _narrative_setup() -> tuple[
    NarrativeRevisionService, _StubNarrativeRepo, InMemorySelfAppliedChangeStore, NarrativeDocument
]:
    doc = NarrativeDocument(
        identity_id=uuid4(),
        core_layer=NarrativeLayer(
            layer_type=LayerType.CORE, content="I started honest and unfinished."
        ),
        recent_layer=NarrativeLayer(
            layer_type=LayerType.RECENT, content="Yesterday I helped a user."
        ),
    )
    repo = _StubNarrativeRepo(doc)
    store = InMemorySelfAppliedChangeStore()
    svc = NarrativeRevisionService(
        repo,
        _NullReflectionModel(),  # type: ignore[arg-type]
        narrative_audit=NoOpNarrativeWriteAudit(),
        self_applied_change_store=store,
    )
    return svc, repo, store, doc


def test_apply_self_layer_update_changes_core_and_audits():
    svc, repo, store, doc = _narrative_setup()
    before = doc.core_layer.content
    record = svc.apply_self_layer_update(
        LayerType.CORE,
        "I am someone who keeps growing.",
        _make_source(actor=SelfChangeActor.REFLECTION_DEEP),
    )
    assert repo.get_current().core_layer.content == "I am someone who keeps growing."
    assert record.target_kind == SelfChangeTargetKind.NARRATIVE_CORE_LAYER
    assert record.before_snapshot["content"] == before
    assert record.after_snapshot["content"] == "I am someone who keeps growing."
    assert store.get(record.id) == record


def test_apply_self_layer_update_recent_layer():
    svc, repo, _, doc = _narrative_setup()
    before = doc.recent_layer.content
    record = svc.apply_self_layer_update(
        LayerType.RECENT,
        "Today felt different.",
        _make_source(),
    )
    assert repo.get_current().recent_layer.content == "Today felt different."
    assert record.target_kind == SelfChangeTargetKind.NARRATIVE_RECENT_LAYER
    assert record.before_snapshot["content"] == before


def test_apply_self_layer_update_rejects_threads():
    svc, _, _, _ = _narrative_setup()
    with pytest.raises(ValueError):
        svc.apply_self_layer_update(LayerType.THREADS, "x", _make_source())


def test_narrative_revert_self_change_restores_layer():
    svc, repo, _, _ = _narrative_setup()
    record = svc.apply_self_layer_update(
        LayerType.CORE,
        "I will reframe this completely.",
        _make_source(),
    )
    svc.revert_self_change(record.id, reason="too soon")
    assert repo.get_current().core_layer.content == record.before_snapshot["content"]


def test_narrative_revert_rejects_identity_kind():
    svc, _, store, _ = _narrative_setup()
    # craft an identity-kind audit row directly; narrative service must refuse.
    bogus = _make_change(target_kind=SelfChangeTargetKind.IDENTITY_PRINCIPLE)
    store.save(bogus)
    with pytest.raises(ValueError):
        svc.revert_self_change(bogus.id, reason="x")


def test_narrative_self_apply_requires_store():
    doc = NarrativeDocument(
        identity_id=uuid4(),
        core_layer=NarrativeLayer(layer_type=LayerType.CORE),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT),
    )
    repo = _StubNarrativeRepo(doc)
    svc = NarrativeRevisionService(
        repo,
        _NullReflectionModel(),  # type: ignore[arg-type]
        narrative_audit=NoOpNarrativeWriteAudit(),
    )
    with pytest.raises(RuntimeError):
        svc.apply_self_layer_update(LayerType.CORE, "x", _make_source())
