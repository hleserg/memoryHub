"""
atman/agent_cli/executor.py
Smart plan execution engine.

Logic per step:
  1. Mini-plan: ask LLM "can I do this? what do I need?"
  2. If not feasible → mark blocked, move on
  3. Implement
  4. Self-assess: "did this succeed?"
  5. If done → check blocked steps BEFORE current → reassess each
     → if now feasible → queue it next (before continuing forward)
  6. If failed → mark blocked, try next

The engine always auto-plans before starting:
  task → full plan → execute step by step

All output goes through a callback so it works in both
Textual (call_from_thread) and headless (CI review mode).
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from enum import Enum

from .memory import (
    STEP_BLOCKED,
    STEP_DONE,
    AgentMemory,
    Plan,
)
from .providers import ProviderRouter
from .rag import RAGIndex

# Output callback: ``fn(text, markup=False)`` for Rich-safe streaming from worker threads.
Output = Callable[[str, bool], None]


class ExecutorInterrupted(Exception):
    """Raised when execution is cancelled via ``stop()`` between phases."""

    def __init__(self, step_index: int) -> None:
        self.step_index = step_index
        super().__init__(f"Executor interrupted at step {step_index}")


def _noop(text: str, markup: bool = False) -> None:
    pass


class RecoveryAction(Enum):
    MISSING_DEPENDENCY = "missing_dependency"
    AMBIGUOUS_REQUIREMENT = "ambiguous_requirement"
    EXTERNAL_UNAVAILABLE = "external_service_unavailable"
    INSUFFICIENT_CONTEXT = "insufficient_context"
    UNKNOWN = "unknown"


BLOCK_ANALYSIS_PROMPT = """Analyze why this plan step is blocked and categorize the reason.

Step: {step}
Blocked reason: {reason}
Recent context:
{recent}

Return JSON only:
{{"category": "missing_dependency|ambiguous_requirement|external_service_unavailable|insufficient_context|unknown",
  "detail": "specific explanation",
  "suggestion": "what to do next"}}"""


# ── Feasibility check ─────────────────────────────────────────────────────────

FEASIBILITY_PROMPT = """You are assessing whether a plan step can be implemented RIGHT NOW.

Task context: {task}
Full plan:
{plan_overview}

Step to assess (index {index}): {step}

Previously completed steps and their results:
{completed}

Previously blocked steps:
{blocked}

Answer with JSON only:
{{
  "feasible": true/false,
  "reason": "brief explanation",
  "mini_plan": ["sub-step 1", "sub-step 2"]  // only if feasible
}}"""


REASSESS_PROMPT = """A step was previously blocked. Reassess whether it's now feasible.

Task context: {task}
Blocked step (index {index}): {step}
Blocked reason was: {blocked_reason}

Steps completed since then:
{completed_since}

Has anything changed that makes this step now possible?
Answer with JSON only:
{{"now_feasible": true/false, "reason": "brief explanation"}}"""


ASSESSMENT_PROMPT = """Assess whether this plan step was successfully implemented.

Step: {step}
Implementation output (summary):
{output_summary}

Did this step succeed? Look for:
- Was relevant code written/modified?
- Are there obvious errors or incomplete implementations?
- Does the output indicate a blocker (import error, missing dependency, etc.)?

Answer with JSON only:
{{"success": true/false, "reason": "brief", "notes": "what was done"}}"""


def _parse_json(text: str) -> dict:
    """Extract JSON from LLM response."""
    text = text.strip()
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Find JSON object in text
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {}


def _plan_overview(plan: Plan) -> str:
    lines = []
    for i, step in enumerate(plan.steps):
        state = plan.get_state(i)
        icon = {"done": "✅", "blocked": "🚫", "in_progress": "⚡", "pending": "⬜"}.get(state, "?")
        lines.append(f"  {icon} {i + 1}. {step}")
    return "\n".join(lines)


def _completed_summary(plan: Plan, up_to: int | None = None) -> str:
    lines = []
    limit = up_to if up_to is not None else len(plan.steps)
    for i in range(limit):
        if plan.get_state(i) == STEP_DONE:
            notes = plan.get_notes(i) or "(done)"
            lines.append(f"  {i + 1}. {plan.steps[i]}: {notes[:100]}")
    return "\n".join(lines) if lines else "  (none yet)"


def _blocked_summary(plan: Plan) -> str:
    lines = []
    for i in range(len(plan.steps)):
        if plan.get_state(i) == STEP_BLOCKED:
            reason = plan.get_blocked_reason(i) or "unknown"
            lines.append(f"  {i + 1}. {plan.steps[i]}: {reason[:100]}")
    return "\n".join(lines) if lines else "  (none)"


# ── Auto-planner ──────────────────────────────────────────────────────────────

AUTO_PLAN_PROMPT = """Create a detailed, ordered implementation plan for this task in the Atman project.

Task: {task}

Context from codebase:
{context}

Rules for plan steps:
- Each step is atomic: one file, one concern, one operation
- Order matters: dependencies come first
- Maximum 8 steps. If more, split into phases.
- Steps should be independently verifiable

Return JSON only:
{{
  "summary": "one sentence summary",
  "steps": [
    "step 1 description",
    "step 2 description"
  ]
}}"""


def auto_plan(task: str, router: ProviderRouter, rag: RAGIndex) -> tuple[str, list[str]]:
    """
    Generate a full plan for a task before execution.
    Returns (summary, steps).
    """
    context = rag.format_context(rag.search(task)) if rag.stats["chunks"] else ""
    prompt = AUTO_PLAN_PROMPT.format(task=task, context=context[:4000])
    raw = router.analyze(prompt)
    data = _parse_json(raw)
    steps = data.get("steps", [])
    summary = data.get("summary", task)
    if not steps:
        # Fallback: treat the whole response as a single step
        steps = [task]
    return summary, steps


# ── Main execution engine ─────────────────────────────────────────────────────


class PlanExecutor:
    """
    Executes a Plan step by step with smart retry logic.

    Flow:
      while steps remain:
        1. find next pending step
        2. assess feasibility (LLM call)
        3. if not feasible → block, continue
        4. implement (LLM stream)
        5. self-assess result
        6. if done → check blocked steps before this one → reassess → maybe retry
        7. if failed → block, continue
    """

    MAX_BLOCK_REASSESS = 3  # max times we retry a previously blocked step

    def __init__(
        self,
        plan: Plan,
        router: ProviderRouter,
        rag: RAGIndex,
        memory: AgentMemory,
        output: Output = _noop,
    ) -> None:
        self.plan = plan
        self.router = router
        self.rag = rag
        self.memory = memory
        self.out = output
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def reset_stop(self) -> None:
        self._stop_event.clear()

    def _should_stop(self) -> bool:
        return self._stop_event.is_set()

    def run(self) -> None:
        """Main execution loop."""
        self.out(f"\n[bold cyan]◆ Executing plan: {self.plan.task}[/bold cyan]")
        self.out(f"[dim]{self.plan.progress_summary()}[/dim]")

        iteration = 0
        max_iterations = len(self.plan.steps) * 3  # safety valve

        while not self._should_stop() and not self.plan.all_done_or_blocked():
            iteration += 1
            if iteration > max_iterations:
                self.out("[yellow]⚠ Max iterations reached — stopping[/yellow]")
                break

            idx = self.plan.next_pending_index()
            if idx is None:
                break

            self._execute_step(idx)

        # Final summary
        done, total = self.plan.progress
        blocked = sum(1 for i in range(total) if self.plan.get_state(i) == STEP_BLOCKED)
        self.out(f"\n[bold]Plan complete:[/bold] {done}/{total} done, {blocked} blocked")
        self.out(self.plan.progress_summary())

        if blocked:
            self.out("\n[yellow]Blocked steps:[/yellow]")
            for i in range(total):
                if self.plan.get_state(i) == STEP_BLOCKED:
                    self.out(
                        f"  🚫 {i + 1}. {self.plan.steps[i]}\n"
                        f"     [dim]{self.plan.get_blocked_reason(i)}[/dim]"
                    )

        self.memory.update_plan(self.plan)

    def _execute_step(self, idx: int) -> None:
        step = self.plan.steps[idx]
        _done, total = self.plan.progress
        self.out(f"\n[bold]Step {idx + 1}/{total}:[/bold] {step}")
        self.out(f"[dim]{self.plan.progress_summary()}[/dim]")

        # Phase 1: Feasibility assessment
        if self._should_stop():
            self.reset_stop()
            raise ExecutorInterrupted(idx)

        self.out("[dim]  ◆ Assessing feasibility...[/dim]")
        feasibility = self._assess_feasibility(idx)

        if not feasibility.get("feasible", True):
            reason = feasibility.get("reason", "LLM determined step is not feasible yet")
            self.out(f"  [yellow]⚠ Blocked:[/yellow] {reason}")
            self.plan.mark_step_blocked(idx, reason)
            self.memory.update_plan(self.plan)
            return

        mini_plan = feasibility.get("mini_plan", [])
        if mini_plan:
            self.out("  [dim]Mini-plan:[/dim]")
            for s in mini_plan:
                self.out(f"    [dim]· {s}[/dim]")

        # Phase 2: Implementation
        if self._should_stop():
            self.reset_stop()
            raise ExecutorInterrupted(idx)

        self.plan.mark_step_in_progress(idx)
        self.memory.update_plan(self.plan)

        context = self.rag.format_context(self.rag.search(f"{self.plan.task} {step}"))
        past = self.memory.recall_context_for_task(step)
        if past:
            context = f"## Past related work\n{past}\n\n{context}"

        recent = self.memory.format_recent_changes_for_context(limit=2)
        if recent:
            context = f"{recent}\n\n{context}"

        implementation_prompt = (
            f"Implement this plan step for the Atman project.\n\n"
            f"Overall task: {self.plan.task}\n"
            f"Current step: {step}\n"
            + (
                "Sub-steps:\n" + "\n".join(f"  - {s}" for s in mini_plan) + "\n"
                if mini_plan
                else ""
            )
            + f"\nCompleted steps so far:\n{_completed_summary(self.plan, up_to=idx)}"
        )

        output_chunks: list[str] = []
        self.out("[dim]  ◆ Implementing...[/dim]")
        for chunk in self.router.code_stream(implementation_prompt, context):
            self.out(chunk, markup=False)
            output_chunks.append(chunk)
        self.out("")  # newline after stream

        full_output = "".join(output_chunks)

        # Phase 3: Self-assessment
        if self._should_stop():
            self.reset_stop()
            raise ExecutorInterrupted(idx)

        self.out("[dim]  ◆ Self-assessing...[/dim]")
        assessment = self._assess_result(step, full_output)
        success = assessment.get("success", True)  # default to success if unclear
        notes = assessment.get("notes", "")
        reason = assessment.get("reason", "")

        if success:
            self.plan.mark_step_done(idx, notes=notes)
            self.memory.update_plan(self.plan)
            self.out(f"  [green]✅ Done[/green] {reason}")

            # Phase 4: Reassess blocked steps that came before
            self._check_and_retry_blocked(idx)
        else:
            self.plan.mark_step_blocked(idx, reason)
            self.memory.update_plan(self.plan)
            recovery_msg = self._handle_blocked(idx, reason)
            self.out(f"  [yellow]{recovery_msg}[/yellow]")

    def _check_and_retry_blocked(self, just_completed_idx: int) -> None:
        """
        After completing a step, look at blocked steps that came before it.
        If any are now feasible, mark them pending so they get picked up next.
        """
        blocked_before = self.plan.blocked_indices_before(just_completed_idx)
        if not blocked_before:
            return

        self.out(f"  [dim]◆ Checking {len(blocked_before)} previously blocked step(s)...[/dim]")

        # Check from most recent to oldest (closer deps more likely to be unblocked)
        for i in reversed(blocked_before):
            if (
                self.plan.get_notes(i)
                and self.plan.get_notes(i).count("reassess") >= self.MAX_BLOCK_REASSESS
            ):
                continue  # gave up on this one

            result = self._reassess_blocked(i, since_index=just_completed_idx)
            if result.get("now_feasible"):
                self.plan.unblock_step(i)
                self.memory.update_plan(self.plan)
                self.out(
                    f"  [cyan]↩ Step {i + 1} unblocked:[/cyan] {result.get('reason', '')}\n"
                    f"    Will execute before continuing"
                )
                # The main loop will pick it up as next_pending (lower index)

    def _assess_feasibility(self, idx: int) -> dict:
        prompt = FEASIBILITY_PROMPT.format(
            task=self.plan.task,
            plan_overview=_plan_overview(self.plan),
            index=idx + 1,
            step=self.plan.steps[idx],
            completed=_completed_summary(self.plan, up_to=idx),
            blocked=_blocked_summary(self.plan),
        )
        raw = self.router.analyze(prompt)
        return _parse_json(raw)

    def _assess_result(self, step: str, output: str) -> dict:
        # Truncate output for prompt
        summary = output[:3000] + "..." if len(output) > 3000 else output
        prompt = ASSESSMENT_PROMPT.format(
            step=step,
            output_summary=summary,
        )
        raw = self.router.analyze(prompt)
        return _parse_json(raw)

    def _reassess_blocked(self, idx: int, since_index: int) -> dict:
        # What was completed since this step was blocked?
        completed_since = []
        for i in range(idx + 1, since_index + 1):
            if self.plan.get_state(i) == STEP_DONE:
                notes = self.plan.get_notes(i) or "(done)"
                completed_since.append(f"  {i + 1}. {self.plan.steps[i]}: {notes[:80]}")

        prompt = REASSESS_PROMPT.format(
            task=self.plan.task,
            index=idx + 1,
            step=self.plan.steps[idx],
            blocked_reason=self.plan.get_blocked_reason(idx),
            completed_since="\n".join(completed_since) if completed_since else "(none)",
        )
        raw = self.router.analyze(prompt)
        return _parse_json(raw)

    def _handle_blocked(self, idx: int, reason: str) -> str:
        """Analyse block reason, return human-readable recovery message."""
        step = self.plan.steps[idx]
        recent_lines: list[str] = []
        for i in range(max(0, idx - 3), idx):
            if self.plan.get_state(i) == STEP_DONE:
                recent_lines.append(
                    f"{i + 1}. {self.plan.steps[i]}: {self.plan.get_notes(i) or ''}"
                )
        recent = "\n".join(recent_lines) or "(none)"

        prompt = BLOCK_ANALYSIS_PROMPT.format(step=step, reason=reason, recent=recent)
        raw = self.router.analyze(prompt)
        data = _parse_json(raw)

        category_raw = str(data.get("category", "unknown"))
        detail = str(data.get("detail", reason))
        suggestion = str(data.get("suggestion", ""))

        try:
            category = RecoveryAction(category_raw)
        except ValueError:
            category = RecoveryAction.UNKNOWN

        messages = {
            RecoveryAction.MISSING_DEPENDENCY: f"Missing: {detail}. Suggest: {suggestion}",
            RecoveryAction.AMBIGUOUS_REQUIREMENT: f"Need clarification: {detail}",
            RecoveryAction.EXTERNAL_UNAVAILABLE: (
                f"Service unavailable: {detail}. Check connection."
            ),
            RecoveryAction.INSUFFICIENT_CONTEXT: (
                f"Need more context: {detail}. Try /ask or provide details."
            ),
            RecoveryAction.UNKNOWN: f"Blocked: {detail}",
        }
        body = messages.get(category, f"Blocked: {detail}")
        return f"⚠ {body}"
