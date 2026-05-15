"""KeyMomentBuilder — constructs KeyMoment from input + optional linguistic enrichment."""
from uuid import UUID

from atman.core.models.entity import KeyMomentEntityLink
from atman.core.models.experience import KeyMoment
from atman.core.models.session import KeyMomentInput
from atman.core.ports.linguistic import KeyMomentAnalysis


class KeyMomentBuilder:
    """Constructs a :class:`KeyMoment` from a :class:`KeyMomentInput` plus optional enrichment.

    Entity links and linguistic markers are layered on top of the base moment
    produced by :meth:`KeyMomentInput.to_key_moment` so that the core conversion
    logic lives in one place and this service handles only the assembly concerns.
    """

    def __init__(self) -> None:
        pass

    def build(
        self,
        input: KeyMomentInput,
        *,
        session_id: UUID,
        agent_id: UUID,
        identity_snapshot_id: UUID | None = None,
        analysis: KeyMomentAnalysis | None = None,
        entity_links: list[KeyMomentEntityLink] | None = None,
    ) -> KeyMoment:
        """Build a fully enriched :class:`KeyMoment` from a :class:`KeyMomentInput`.

        Parameters
        ----------
        input:
            Raw key-moment input captured during the session.
        session_id:
            The session this moment belongs to.
        agent_id:
            Agent that owns the moment (used when building entity links).
        identity_snapshot_id:
            Identity snapshot active at recording time; may be None for
            sessions started before snapshot tracking was introduced.
        analysis:
            Optional linguistic analysis to fold into structured_markers.
        entity_links:
            Pre-built entity links, ignored here but accepted for symmetry
            (the caller may attach them to the store separately).
        """
        moment = input.to_key_moment()

        moment.session_id = session_id
        moment.identity_snapshot_id = identity_snapshot_id
        moment.incomplete_coloring = input.incomplete_coloring

        if analysis is not None:
            markers: dict = {
                "entities": [
                    (e.text, e.entity_type.value, e.confidence)
                    for e in analysis.entities
                ],
                "topic_labels": analysis.topic_labels,
                "cognitive_load": analysis.cognitive_load,
                "boundary_event": analysis.boundary_event,
                "trust_signal": analysis.trust_signal,
                "principle_invocations": analysis.principle_invocations,
            }
            moment.structured_markers = markers
            moment.structured_markers_version = "1.0"

        return moment

    def build_entity_links(
        self,
        moment: KeyMoment,
        analysis: KeyMomentAnalysis,
        agent_id: UUID,
        entity_ids: list[tuple[UUID, str]],
    ) -> list[KeyMomentEntityLink]:
        """Build :class:`KeyMomentEntityLink` records from resolved entity IDs.

        Parameters
        ----------
        moment:
            The key moment to link against.
        analysis:
            Linguistic analysis result (not directly used here, available for
            future signal-based involvement overrides).
        agent_id:
            Agent that owns the entities.
        entity_ids:
            Pairs of ``(entity_id, involvement)`` resolved by the EntityRegistry.
            ``involvement`` must be one of the values accepted by
            :class:`~atman.core.models.entity.KeyMomentEntityLink`.
        """
        links: list[KeyMomentEntityLink] = []
        for entity_id, involvement in entity_ids:
            link = KeyMomentEntityLink(
                key_moment_id=moment.id,
                entity_id=entity_id,
                agent_id=agent_id,
                involvement=involvement,
            )
            links.append(link)
        return links
