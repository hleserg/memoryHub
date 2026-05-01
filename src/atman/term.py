"""
Rich-based terminal output for CLI and demos.

Keeps markup-safe printing for help text and user-provided strings.
"""

from __future__ import annotations

import os
import time

from rich import box
from rich.console import Console, Group
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.theme import Theme

from atman.core.models import ExperienceRecord, FactRecord

_THEME = Theme(
    {
        "term.ok": "bold green",
        "term.err": "bold red",
        "term.warn": "yellow",
        "term.title": "bold cyan",
        "term.dim": "dim",
        "term.label": "bold",
        "term.border": "cyan",
    }
)

console = Console(theme=_THEME)
console_err = Console(theme=_THEME, stderr=True)

# Seconds; clamped so a typo cannot hang the terminal.
_DEMO_PACE_DEFAULT = 0.45
_DEMO_PACE_MAX = 3.0


def demo_pace() -> None:
    """
    Optional pause between demo beats for a clearer step-by-step reveal.

    Enable with env ``ATMAN_DEMO_PACE``: ``1`` / ``yes`` / ``on`` uses a default
    delay (~0.45s), or set a positive float (e.g. ``0.7``). ``0`` / ``off`` / unset = no pause.
    """
    raw = (os.environ.get("ATMAN_DEMO_PACE") or "").strip().lower()
    if not raw or raw in ("0", "no", "false", "off"):
        return
    if raw in ("1", "yes", "true", "on"):
        delay = _DEMO_PACE_DEFAULT
    else:
        try:
            delay = float(raw)
        except ValueError:
            return
    if delay <= 0:
        return
    time.sleep(min(delay, _DEMO_PACE_MAX))


def print_ok(message: str) -> None:
    console.print(f"[term.ok]✓[/term.ok] {message}")


def print_err(message: str) -> None:
    console_err.print(f"[term.err]✗[/term.err] {message}")


def print_warn(message: str) -> None:
    console_err.print(f"[term.warn]![/term.warn] {message}")


def print_info(message: str) -> None:
    console.print(message)


def print_banner(title: str, subtitle: str | None = None) -> None:
    body = title if subtitle is None else f"{title}\n[term.dim]{subtitle}[/term.dim]"
    console.print(
        Panel.fit(
            body,
            border_style="term.border",
            padding=(1, 2),
        )
    )


def print_section(title: str) -> None:
    console.print(Rule(f"[term.title]{title}[/term.title]", style="term.border"))


def print_help_text(text: str) -> None:
    console.print(text, markup=False, highlight=False)


def _indent_width(prefix: str) -> int:
    return len(prefix.expandtabs())


def print_fact(fact: FactRecord, prefix: str = "") -> None:
    table = Table(show_header=False, box=box.SIMPLE, pad_edge=False, padding=(0, 1, 0, 0))
    table.add_column(style="term.label", justify="right", min_width=12)
    table.add_column(ratio=1)
    tags = ", ".join(fact.tags) if fact.tags else "—"
    table.add_row("ID", str(fact.id))
    table.add_row("Содержание", fact.content)
    table.add_row("Источник", fact.source)
    table.add_row("Теги", tags)
    table.add_row("Создан", fact.created_at.strftime("%Y-%m-%d %H:%M:%S"))
    if fact.relations:
        rel_lines = "\n".join(f"• {rel.relation_type} → {rel.target_id}" for rel in fact.relations)
        table.add_row("Связи", rel_lines)
    if fact.metadata:
        table.add_row("Метаданные", str(fact.metadata))
    block: Group | Padding = Group(table)
    if prefix:
        block = Padding(table, pad=(0, 0, 0, _indent_width(prefix)))
    console.print(block)
    console.print()


def print_experience_record(record: ExperienceRecord, prefix: str = "") -> None:
    exp = record.experience
    main = Table(show_header=False, box=box.ROUNDED, pad_edge=False, padding=(0, 1, 0, 0))
    main.add_column(style="term.label", justify="right", min_width=14)
    main.add_column(ratio=1)
    main.add_row("ID", str(exp.id))
    main.add_row("Session", str(exp.session_id))
    main.add_row("Recorded", exp.timestamp.strftime("%Y-%m-%d %H:%M:%S"))
    main.add_row("Recorded by", exp.recorded_by)
    main.add_row("Importance", f"{exp.importance:.2f}")
    main.add_row("Salience", f"{exp.salience:.2f}")
    main.add_row("Access count", str(exp.access_count))
    main.add_row("Last accessed", exp.last_accessed_at.strftime("%Y-%m-%d %H:%M:%S"))
    main.add_row("Incomplete coloring", str(exp.incomplete_coloring))

    parts: list[Table | Panel] = [main]

    for i, moment in enumerate(exp.key_moments, 1):
        felt = (
            f"valence={moment.how_i_felt.emotional_valence:.2f}, "
            f"intensity={moment.how_i_felt.emotional_intensity:.2f}, "
            f"depth={moment.how_i_felt.depth.value}"
        )
        lines = [
            moment.what_happened,
            "",
            f"[term.dim]When[/term.dim] {moment.when.strftime('%Y-%m-%d %H:%M:%S')}",
            f"[term.dim]Felt[/term.dim] {felt}",
            f"[term.dim]Why it matters[/term.dim] {moment.why_it_matters}",
        ]
        if moment.values_touched:
            lines.append(f"[term.dim]Values[/term.dim] {', '.join(moment.values_touched)}")
        if moment.principles_confirmed:
            lines.append(f"[term.dim]Confirmed[/term.dim] {', '.join(moment.principles_confirmed)}")
        if moment.principles_questioned:
            lines.append(
                f"[term.dim]Questioned[/term.dim] {', '.join(moment.principles_questioned)}"
            )
        if moment.what_changed:
            lines.append(f"[term.dim]Changed[/term.dim] {moment.what_changed}")
        parts.append(
            Panel(
                "\n".join(lines),
                title=f"[term.title]Key moment {i}[/term.title]",
                border_style="dim",
                padding=(1, 2),
            )
        )

    if exp.reframing_notes:
        notes = Table(title="Reframing notes", box=box.ROUNDED, show_lines=True, padding=(0, 1))
        notes.add_column("#", justify="right", style="term.dim", width=3)
        notes.add_column("Added", style="term.dim")
        notes.add_column("Type")
        notes.add_column("Reflection", ratio=2)
        for i, note in enumerate(exp.reframing_notes, 1):
            trig = (
                f"\n[term.dim]Triggered by[/term.dim] {note.triggered_by}"
                if note.triggered_by
                else ""
            )
            notes.add_row(
                str(i),
                note.added_at.strftime("%Y-%m-%d %H:%M:%S"),
                note.reflection_type,
                f"{note.reflection}{trig}",
            )
        parts.append(notes)

    group: Group | Padding = Group(*parts)
    if prefix:
        group = Padding(Group(*parts), pad=(0, 0, 0, _indent_width(prefix)))
    console.print(group)
    console.print()


def print_salience_table(rows: list[tuple[int, float]], title: str | None = None) -> None:
    table = Table(title=title, box=box.ROUNDED, show_header=True, header_style="term.label")
    table.add_column("Days", justify="right")
    table.add_column("Salience", justify="right")
    for days, sal in rows:
        table.add_row(str(days), f"{sal:.4f}")
    console.print(table)
