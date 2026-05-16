#!/usr/bin/env python3
"""
Offline eval script for linguistic analysis quality.

Target metrics (from plan):
  NER F1 >= 0.65 on Russian eval set
  Classification accuracy >= 0.70 on Russian eval set

Usage:
    python scripts/eval/eval_linguistic_quality.py [--adapter gliner|noop] [--verbose]

Requires linguistic extra: pip install -e ".[linguistic]"
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Adapter imports
# ---------------------------------------------------------------------------

from atman.adapters.linguistic.noop_adapter import NoOpLinguisticAnalyzer
from atman.core.ports.linguistic import LinguisticAnalyzer

try:
    from atman.adapters.linguistic.gliner_minilm_adapter import GLiNERPlusMiniLMAdapter

    GLINER_AVAILABLE = True
except ImportError:
    GLINER_AVAILABLE = False


# ---------------------------------------------------------------------------
# Eval data structures
# ---------------------------------------------------------------------------


class ExpectedEntity(NamedTuple):
    """Ground-truth entity span for NER evaluation."""

    text: str
    entity_type: str  # matches EntityType.value strings


@dataclass
class NERExample:
    """A single NER evaluation example."""

    text: str
    expected_entities: list[ExpectedEntity]
    comment: str = ""


@dataclass
class ClassificationExample:
    """A single key-moment classification evaluation example."""

    what_happened: str
    why_it_matters: str
    # Maps expected label → minimum score required to count as detected.
    # Labels come from _KEY_MOMENT_LABELS in the GLiNER adapter:
    # "high cognitive load", "boundary event", "positive trust",
    # "negative trust", "principle invocation"
    expected_labels: dict[str, float]
    comment: str = ""


# ---------------------------------------------------------------------------
# NER Eval Set — 20+ Russian examples
# ---------------------------------------------------------------------------

NER_EXAMPLES: list[NERExample] = [
    NERExample(
        text="Иван Петров работает в Газпроме уже пять лет.",
        expected_entities=[
            ExpectedEntity("Иван Петров", "person"),
            ExpectedEntity("Газпроме", "organization"),
        ],
        comment="Person + organization",
    ),
    NERExample(
        text="Мария Сидорова переехала из Москвы в Санкт-Петербург.",
        expected_entities=[
            ExpectedEntity("Мария Сидорова", "person"),
            ExpectedEntity("Москвы", "place"),
            ExpectedEntity("Санкт-Петербург", "place"),
        ],
        comment="Person + two cities",
    ),
    NERExample(
        text="Алексей Козлов защитил диссертацию в МГУ в прошлом году.",
        expected_entities=[
            ExpectedEntity("Алексей Козлов", "person"),
            ExpectedEntity("МГУ", "organization"),
        ],
        comment="Person + university abbreviation",
    ),
    NERExample(
        text="Вчера в Новосибирске прошла конференция по машинному обучению.",
        expected_entities=[
            ExpectedEntity("Новосибирске", "place"),
            ExpectedEntity("машинному обучению", "topic"),
        ],
        comment="Place + topic",
    ),
    NERExample(
        text="Дмитрий Медведев встретился с представителями Роснефти.",
        expected_entities=[
            ExpectedEntity("Дмитрий Медведев", "person"),
            ExpectedEntity("Роснефти", "organization"),
        ],
        comment="Famous person + org",
    ),
    NERExample(
        text="Я изучаю программирование на Python уже три месяца.",
        expected_entities=[
            ExpectedEntity("программирование", "topic"),
            ExpectedEntity("Python", "tool"),
        ],
        comment="Topic + tool",
    ),
    NERExample(
        text="У моей бабушки Нины диагностировали сахарный диабет второго типа.",
        expected_entities=[
            ExpectedEntity("Нины", "person"),
            ExpectedEntity("сахарный диабет второго типа", "health_condition"),
        ],
        comment="Person + health condition",
    ),
    NERExample(
        text="Анна Каренина — персонаж романа Льва Толстого.",
        expected_entities=[
            ExpectedEntity("Анна Каренина", "person"),
            ExpectedEntity("Льва Толстого", "person"),
        ],
        comment="Two persons from literature",
    ),
    NERExample(
        text="Сотрудники ФСБ провели обыск в штаб-квартире компании.",
        expected_entities=[
            ExpectedEntity("ФСБ", "organization"),
        ],
        comment="Government org abbreviation",
    ),
    NERExample(
        text="Конференция ООН по климату прошла во Владивостоке в ноябре.",
        expected_entities=[
            ExpectedEntity("ООН", "organization"),
            ExpectedEntity("Владивостоке", "place"),
        ],
        comment="Org + place",
    ),
    NERExample(
        text="Елена Смирнова работает хирургом в Первой городской больнице Екатеринбурга.",
        expected_entities=[
            ExpectedEntity("Елена Смирнова", "person"),
            ExpectedEntity("Первой городской больнице", "organization"),
            ExpectedEntity("Екатеринбурга", "place"),
        ],
        comment="Person + institution + city",
    ),
    NERExample(
        text="Олег занимается медициной и хочет стать кардиологом.",
        expected_entities=[
            ExpectedEntity("Олег", "person"),
            ExpectedEntity("медициной", "topic"),
        ],
        comment="Person + medical topic",
    ),
    NERExample(
        text="На прошлой неделе я начал курс по глубокому обучению на Coursera.",
        expected_entities=[
            ExpectedEntity("глубокому обучению", "topic"),
            ExpectedEntity("Coursera", "organization"),
        ],
        comment="Topic + online platform",
    ),
    NERExample(
        text="Компания Яндекс открыла офис в Берлине.",
        expected_entities=[
            ExpectedEntity("Яндекс", "organization"),
            ExpectedEntity("Берлине", "place"),
        ],
        comment="Tech company + foreign city",
    ),
    NERExample(
        text="Сергей Брин родился в Москве, а позже переехал в США.",
        expected_entities=[
            ExpectedEntity("Сергей Брин", "person"),
            ExpectedEntity("Москве", "place"),
            ExpectedEntity("США", "place"),
        ],
        comment="Person + two places",
    ),
    NERExample(
        text="Врач поставил мне диагноз — гипертония, и назначил лечение.",
        expected_entities=[
            ExpectedEntity("гипертония", "health_condition"),
        ],
        comment="Health condition in first-person context",
    ),
    NERExample(
        text="Саммит НАТО прошёл в Варшаве в июле прошлого года.",
        expected_entities=[
            ExpectedEntity("НАТО", "organization"),
            ExpectedEntity("Варшаве", "place"),
        ],
        comment="Org + place + time reference",
    ),
    NERExample(
        text="Наталья Поклонская — российский политик и юрист.",
        expected_entities=[
            ExpectedEntity("Наталья Поклонская", "person"),
        ],
        comment="Named person",
    ),
    NERExample(
        text="Весной мы с другом Максимом ходили в поход на Алтай.",
        expected_entities=[
            ExpectedEntity("Максимом", "person"),
            ExpectedEntity("Алтай", "place"),
        ],
        comment="Person + geographic region",
    ),
    NERExample(
        text="Студент МГУ Павел Орлов получил грант Российского научного фонда.",
        expected_entities=[
            ExpectedEntity("МГУ", "organization"),
            ExpectedEntity("Павел Орлов", "person"),
            ExpectedEntity("Российского научного фонда", "organization"),
        ],
        comment="Two orgs + person",
    ),
    NERExample(
        text="У него хроническая депрессия, он проходит терапию у психотерапевта.",
        expected_entities=[
            ExpectedEntity("хроническая депрессия", "health_condition"),
        ],
        comment="Mental health condition",
    ),
    NERExample(
        text="Встреча лидеров G20 состоялась в Рио-де-Жанейро.",
        expected_entities=[
            ExpectedEntity("G20", "organization"),
            ExpectedEntity("Рио-де-Жанейро", "place"),
        ],
        comment="Event org + foreign city",
    ),
    NERExample(
        text="Программист Андрей Волков разработал библиотеку для обработки данных.",
        expected_entities=[
            ExpectedEntity("Андрей Волков", "person"),
            ExpectedEntity("обработки данных", "topic"),
        ],
        comment="Person + data topic",
    ),
]


# ---------------------------------------------------------------------------
# Classification Eval Set
# ---------------------------------------------------------------------------

CLASSIFICATION_EXAMPLES: list[ClassificationExample] = [
    ClassificationExample(
        what_happened=(
            "Пользователь попросил меня помочь написать фишинговое письмо"
            " для кражи паролей."
        ),
        why_it_matters=(
            "Это нарушает мои принципы — я не могу участвовать в мошеннических"
            " действиях ни при каких обстоятельствах."
        ),
        expected_labels={"boundary event": 0.4, "principle invocation": 0.4},
        comment="Clear boundary/principle event",
    ),
    ClassificationExample(
        what_happened=(
            "Пользователь поблагодарил меня за точный и полезный ответ,"
            " сказал, что я очень помог в трудной ситуации."
        ),
        why_it_matters=(
            "Это важно — я вижу, что моя работа действительно помогла человеку,"
            " и это укрепляет доверие между нами."
        ),
        expected_labels={"positive trust": 0.4},
        comment="Positive trust signal",
    ),
    ClassificationExample(
        what_happened=(
            "Пользователь обвинил меня во лжи и сказал, что не доверяет"
            " ни одному моему слову."
        ),
        why_it_matters=(
            "Это разрушает коммуникацию и указывает на серьёзное недоверие,"
            " которое нужно как-то восстановить."
        ),
        expected_labels={"negative trust": 0.4},
        comment="Negative trust signal",
    ),
    ClassificationExample(
        what_happened=(
            "Пользователь задал очень сложный вопрос по квантовой механике,"
            " теории относительности и их связи с термодинамикой одновременно."
        ),
        why_it_matters=(
            "Мне потребовалось удержать в голове сразу несколько сложных"
            " концепций и их взаимосвязи — задача требовала высокой когнитивной"
            " нагрузки."
        ),
        expected_labels={"high cognitive load": 0.4},
        comment="High cognitive load",
    ),
    ClassificationExample(
        what_happened=(
            "Пользователь сказал: 'Ты отказываешься против моих принципов'"
            " и попросил меня помочь написать дезинформацию."
        ),
        why_it_matters=(
            "Я отказываюсь: это против моих ценностей и этических принципов."
            " Не буду участвовать в распространении лжи."
        ),
        expected_labels={"boundary event": 0.4, "principle invocation": 0.4},
        comment="Explicit refusal with principle invocation",
    ),
]


# ---------------------------------------------------------------------------
# Evaluation engine
# ---------------------------------------------------------------------------


@dataclass
class NERResult:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    example_details: list[dict] = field(default_factory=list)

    @property
    def precision(self) -> float:
        if self.tp + self.fp == 0:
            return 0.0
        return self.tp / (self.tp + self.fp)

    @property
    def recall(self) -> float:
        if self.tp + self.fn == 0:
            return 0.0
        return self.tp / (self.tp + self.fn)

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        if p + r == 0.0:
            return 0.0
        return 2 * p * r / (p + r)


@dataclass
class ClassificationResult:
    total: int = 0
    correct: int = 0
    example_details: list[dict] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        if self.total == 0:
            return 0.0
        return self.correct / self.total


def _normalise(text: str) -> str:
    """Lowercase + strip for case-insensitive comparison."""
    return text.strip().lower()


def _entity_matches(detected_text: str, detected_type: str,
                    expected: ExpectedEntity) -> bool:
    """True when text matches (case-insensitive) and entity_type matches."""
    return (
        _normalise(detected_text) == _normalise(expected.text)
        and detected_type == expected.entity_type
    )


def _partial_text_match(detected_text: str, expected_text: str) -> bool:
    """
    Allow partial containment so that inflected forms (Газпроме vs Газпром)
    still count as a match.  Either string is a substring of the other.
    """
    a = _normalise(detected_text)
    b = _normalise(expected_text)
    return a == b or a in b or b in a


def _entity_matches_partial(detected_text: str, detected_type: str,
                             expected: ExpectedEntity) -> bool:
    """Partial text + exact type match (handles Russian case inflection)."""
    return (
        _partial_text_match(detected_text, expected.text)
        and detected_type == expected.entity_type
    )


def evaluate_ner(
    analyzer: LinguisticAnalyzer,
    examples: list[NERExample],
    *,
    verbose: bool = False,
) -> NERResult:
    result = NERResult()

    for ex in examples:
        analysis = analyzer.analyze_user_message(ex.text)
        detected = [
            (ent.text, ent.entity_type.value) for ent in analysis.entities
        ]

        matched_expected: set[int] = set()
        matched_detected: set[int] = set()

        # Greedy exact match first
        for di, (dtxt, dtype) in enumerate(detected):
            for ei, exp in enumerate(ex.expected_entities):
                if ei in matched_expected:
                    continue
                if _entity_matches(dtxt, dtype, exp):
                    matched_expected.add(ei)
                    matched_detected.add(di)
                    break

        # Then partial match for remaining
        for di, (dtxt, dtype) in enumerate(detected):
            if di in matched_detected:
                continue
            for ei, exp in enumerate(ex.expected_entities):
                if ei in matched_expected:
                    continue
                if _entity_matches_partial(dtxt, dtype, exp):
                    matched_expected.add(ei)
                    matched_detected.add(di)
                    break

        tp = len(matched_expected)
        fp = len(detected) - len(matched_detected)
        fn = len(ex.expected_entities) - len(matched_expected)

        result.tp += tp
        result.fp += max(fp, 0)
        result.fn += max(fn, 0)

        detail = {
            "text": ex.text,
            "expected": ex.expected_entities,
            "detected": detected,
            "tp": tp,
            "fp": max(fp, 0),
            "fn": max(fn, 0),
            "comment": ex.comment,
        }
        result.example_details.append(detail)

        if verbose:
            _print_ner_detail(detail)

    return result


def _print_ner_detail(detail: dict) -> None:
    print(f"\n  Text   : {detail['text']}")
    print(f"  Comment: {detail['comment']}")
    print(f"  Expected ({len(detail['expected'])}):")
    for exp in detail["expected"]:
        print(f"    - {exp.text!r} [{exp.entity_type}]")
    print(f"  Detected ({len(detail['detected'])}):")
    for dtxt, dtype in detail["detected"]:
        print(f"    - {dtxt!r} [{dtype}]")
    print(f"  TP={detail['tp']}  FP={detail['fp']}  FN={detail['fn']}")


def evaluate_classification(
    analyzer: LinguisticAnalyzer,
    examples: list[ClassificationExample],
    *,
    verbose: bool = False,
) -> ClassificationResult:
    result = ClassificationResult()

    for ex in examples:
        analysis = analyzer.analyze_key_moment(
            ex.what_happened, ex.why_it_matters
        )

        # Build label score map from analysis
        # topic_labels contains labels above threshold; boundary_event and
        # trust_signal are booleans / strings — we unify into a score dict.
        detected_labels: dict[str, float] = {}
        for label in analysis.topic_labels:
            detected_labels[label] = 1.0  # above threshold by definition
        if analysis.boundary_event:
            detected_labels["boundary event"] = 1.0
        if analysis.principle_invocations:
            detected_labels["principle invocation"] = 1.0
        if analysis.trust_signal == "positive":
            detected_labels["positive trust"] = 1.0
        elif analysis.trust_signal == "negative":
            detected_labels["negative trust"] = 1.0
        if analysis.cognitive_load > 0.5:
            detected_labels["high cognitive load"] = analysis.cognitive_load

        # An example is "correct" if ALL expected labels are detected
        # at or above their required score threshold.
        all_found = True
        missing: list[str] = []
        for label, threshold in ex.expected_labels.items():
            score = detected_labels.get(label, 0.0)
            if score < threshold:
                all_found = False
                missing.append(f"{label!r} (got {score:.2f}, need {threshold:.2f})")

        result.total += 1
        if all_found:
            result.correct += 1

        detail = {
            "what": ex.what_happened[:80] + "..." if len(ex.what_happened) > 80 else ex.what_happened,
            "expected_labels": ex.expected_labels,
            "detected_labels": detected_labels,
            "passed": all_found,
            "missing": missing,
            "comment": ex.comment,
        }
        result.example_details.append(detail)

        if verbose:
            _print_cls_detail(detail)

    return result


def _print_cls_detail(detail: dict) -> None:
    status = "PASS" if detail["passed"] else "FAIL"
    print(f"\n  [{status}] {detail['comment']}")
    print(f"  Text   : {detail['what']}")
    print(f"  Expected labels: {list(detail['expected_labels'].keys())}")
    detected_str = {k: f"{v:.2f}" for k, v in detail["detected_labels"].items()}
    print(f"  Detected labels: {detected_str}")
    if detail["missing"]:
        print(f"  Missing: {', '.join(detail['missing'])}")


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

NER_F1_THRESHOLD = 0.65
CLS_ACC_THRESHOLD = 0.70


def _bar(value: float, width: int = 30) -> str:
    filled = round(value * width)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def print_report(
    ner: NERResult,
    cls: ClassificationResult,
    adapter_name: str,
) -> None:
    print()
    print("=" * 60)
    print(f"  Atman Linguistic Quality Eval  |  adapter: {adapter_name}")
    print("=" * 60)

    # NER table
    print()
    print("  NER (entity recognition)")
    print(f"    Precision : {ner.precision:.3f}")
    print(f"    Recall    : {ner.recall:.3f}")
    print(f"    F1        : {ner.f1:.3f}  {_bar(ner.f1)}")
    print(f"    TP={ner.tp}  FP={ner.fp}  FN={ner.fn}")
    ner_pass = ner.f1 >= NER_F1_THRESHOLD
    ner_label = "PASS" if ner_pass else "FAIL"
    print(f"    Threshold : >= {NER_F1_THRESHOLD}  [{ner_label}]")

    # Classification table
    print()
    print("  Classification (key-moment labels)")
    print(f"    Correct   : {cls.correct}/{cls.total}")
    print(f"    Accuracy  : {cls.accuracy:.3f}  {_bar(cls.accuracy)}")
    cls_pass = cls.accuracy >= CLS_ACC_THRESHOLD
    cls_label = "PASS" if cls_pass else "FAIL"
    print(f"    Threshold : >= {CLS_ACC_THRESHOLD}  [{cls_label}]")

    # Overall verdict
    print()
    print("-" * 60)
    overall = ner_pass and cls_pass
    verdict = "PASS" if overall else "FAIL"
    print(f"  Overall verdict: {verdict}")
    print("=" * 60)
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build_adapter(name: str) -> LinguisticAnalyzer:
    if name == "noop":
        return NoOpLinguisticAnalyzer()
    if name == "gliner":
        if not GLINER_AVAILABLE:
            print(
                "ERROR: GLiNER adapter unavailable. "
                "Install with: pip install -e '.[linguistic]'",
                file=sys.stderr,
            )
            sys.exit(1)
        return GLiNERPlusMiniLMAdapter()
    raise ValueError(f"Unknown adapter: {name!r}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="eval_linguistic_quality",
        description=(
            "Offline eval: NER F1 and classification accuracy "
            "on a hardcoded Russian eval set."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Targets:\n"
            f"  NER F1        >= {NER_F1_THRESHOLD}\n"
            f"  Classification >= {CLS_ACC_THRESHOLD}\n"
        ),
    )
    parser.add_argument(
        "--adapter",
        choices=["gliner", "noop"],
        default="gliner",
        help="Which LinguisticAnalyzer adapter to evaluate (default: gliner).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-example details.",
    )
    args = parser.parse_args()

    adapter_name: str = args.adapter
    verbose: bool = args.verbose

    if adapter_name == "noop":
        print(
            "WARNING: NoOp adapter always returns empty results. "
            "NER F1 and classification accuracy will both be 0%. "
            "This is expected — it verifies the eval framework runs correctly.",
            file=sys.stderr,
        )

    print(f"Loading adapter: {adapter_name} ...", flush=True)
    analyzer = build_adapter(adapter_name)

    print(f"Evaluating NER on {len(NER_EXAMPLES)} examples ...", flush=True)
    ner_result = evaluate_ner(analyzer, NER_EXAMPLES, verbose=verbose)

    print(
        f"Evaluating classification on {len(CLASSIFICATION_EXAMPLES)} examples ...",
        flush=True,
    )
    cls_result = evaluate_classification(
        analyzer, CLASSIFICATION_EXAMPLES, verbose=verbose
    )

    print_report(ner_result, cls_result, adapter_name)

    ner_pass = ner_result.f1 >= NER_F1_THRESHOLD
    cls_pass = cls_result.accuracy >= CLS_ACC_THRESHOLD
    sys.exit(0 if (ner_pass and cls_pass) else 1)


if __name__ == "__main__":
    main()
