"""mREBEL-based EntityRelationExtractor — relation extraction via Babelscape/mrebel-large.

Gated behind the `linguistic` optional extra. If `transformers` is not
installed the constructor raises ImportError so callers can fall back to
a rules-based extractor or a no-op.
"""

from __future__ import annotations

import logging
from typing import Any

from typing_extensions import override

from atman.core.ports.entity_relations import EntityRelationExtractor, ExtractedRelation
from atman.core.ports.linguistic import DetectedEntity

logger = logging.getLogger(__name__)

try:
    from transformers import pipeline as _hf_pipeline  # type: ignore[import-untyped]

    _TRANSFORMERS_AVAILABLE = True
except ImportError:
    _hf_pipeline = None  # type: ignore[assignment]
    _TRANSFORMERS_AVAILABLE = False


class MRebelRelationAdapter(EntityRelationExtractor):
    """Relation extraction via `Babelscape/mrebel-large` (multilingual REBEL).

    The HF pipeline is loaded lazily on first call. The model outputs
    triplets of the form ``<triplet> subj <subj_type> obj <obj_type> relation_label``,
    which this adapter parses and matches to the provided entity spans.

    Falls back to an empty result list when the model fails to load or
    when no candidate entities are provided.
    """

    def __init__(
        self,
        model_name: str = "Babelscape/mrebel-large",
        device: str = "cpu",
        confidence_threshold: float = 0.5,
    ) -> None:
        if not _TRANSFORMERS_AVAILABLE:
            raise ImportError(
                "transformers is not installed. Install with: "
                "pip install 'atman[linguistic]' or 'pip install transformers'"
            )
        self._model_name = model_name
        self._device = device
        self._threshold = confidence_threshold
        self._pipeline: Any = None

    def _get_pipeline(self) -> Any:
        """Lazy-load the HF text2text-generation pipeline on first use."""
        if self._pipeline is not None:
            return self._pipeline
        logger.info("Loading mREBEL model %s …", self._model_name)
        try:
            self._pipeline = _hf_pipeline(  # type: ignore[operator]
                "text2text-generation",
                model=self._model_name,
                tokenizer=self._model_name,
                device=self._device,
            )
        except Exception:
            logger.exception("Failed to load mREBEL model %s", self._model_name)
            return None
        return self._pipeline

    @override
    def extract_relations(
        self,
        text: str,
        entities: list[DetectedEntity],
    ) -> list[ExtractedRelation]:
        """Run mREBEL on `text`, match generated triplets to known entity spans."""
        if not text.strip() or len(entities) < 2:
            return []
        pipe = self._get_pipeline()
        if pipe is None:
            return []
        try:
            outputs = pipe(
                text,
                max_length=256,
                num_beams=3,
                return_tensors=False,
                clean_up_tokenization_spaces=True,
            )
        except Exception:
            logger.exception("mREBEL inference failed for text of length %d", len(text))
            return []

        if not outputs or not isinstance(outputs, list):
            return []
        generated = str(outputs[0].get("generated_text", "")) if outputs else ""
        triplets = _parse_rebel_triplets(generated)

        # Match triplet subj/obj strings back to detected entities by canonical
        # text (case-insensitive). Unmatched triplets are dropped.
        entity_by_text: dict[str, DetectedEntity] = {e.text.lower(): e for e in entities}
        relations: list[ExtractedRelation] = []
        for subj_text, obj_text, relation_label in triplets:
            subj = entity_by_text.get(subj_text.lower())
            obj = entity_by_text.get(obj_text.lower())
            if subj is None or obj is None:
                continue
            if subj.text.lower() == obj.text.lower():
                continue
            relations.append(
                ExtractedRelation(
                    subject=subj,
                    object=obj,
                    relation_type=relation_label,
                    confidence=1.0,
                    learned_by="mrebel",
                )
            )
        return relations


def _parse_rebel_triplets(decoded: str) -> list[tuple[str, str, str]]:
    """Parse a REBEL-formatted ``<triplet> subj <subj_type> obj <obj_type> rel`` string.

    REBEL/mREBEL emit triplets delimited by ``<triplet>``. Within each triplet,
    the subject is followed by ``<subj_type>`` and the object by ``<obj_type>``,
    then the relation label. Type tags are discarded here; only ``(subj, obj,
    relation)`` is returned.
    """
    if not decoded:
        return []
    out: list[tuple[str, str, str]] = []
    for chunk in decoded.split("<triplet>")[1:]:
        chunk = chunk.strip()
        if not chunk:
            continue
        if "<subj>" in chunk:
            subj_part, _, rest = chunk.partition("<subj>")
        elif "<subj_type>" in chunk:
            subj_part, _, rest = chunk.partition("<subj_type>")
        else:
            # No subject delimiter — skip
            continue
        if "<obj>" in rest:
            obj_part, _, relation_part = rest.partition("<obj>")
        elif "<obj_type>" in rest:
            obj_part, _, relation_part = rest.partition("<obj_type>")
        else:
            continue
        subj_text = subj_part.strip()
        obj_text = obj_part.strip()
        relation = relation_part.strip().split()[0] if relation_part.strip() else ""
        if not subj_text or not obj_text or not relation:
            continue
        out.append((subj_text, obj_text, relation))
    return out
