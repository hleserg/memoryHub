## Source: SYSTEM.md

# ATMAN

## Architecture of AI Agent's Psychological Layer

*Technical description of system components and interfaces (updated 28.04.2026)*

[[ru](SYSTEM-ru.md)] — *Русская версия / Russian version*

---

## Introduction

Atman is a psychological layer system for an AI agent. Its task is not to execute tasks, but to be the one who executes them. It works on top of mem0, using it as **pure factual storage**, and then assembles from facts: experience, reflection, skills, and identity.

**Core principle:** The lower agent acts. Atman — exists.

**Critical change (28.04.2026):** Experience Store and Experience Processor were redesigned. Experience is colored **first-hand in real-time**, not retrospectively. Experience Processor was removed — its functions were distributed between Session Manager and Reflection Engine.

---

## SYSTEM COMPONENTS (7 components)

### 1. Factual Memory / mem0

**Purpose:** Pure factual storage. Here live verifiable facts, stable states, extractable relationships and anchor elements of history — without interpretations, without self-naming, without psychological commentary.

mem0 should not mix:

* fact and conclusion;
* observation and reflection;
* habit and principle;
* event and its meaning.

Its role is to store what can be restored, compared and linked. Not "what this means", but "what was".

**Architectural role:**

* embeddings provide semantic recall — finding similar and close;
* graph memory holds relations — who/what/when/with what connected;
* structured facts ensure verifiability and stability;
* together they give factual connectivity, not just record archive.

**How this works in Atman:**

* **identity loop** uses facts to restore selfhood between sessions;
* **skill loop** extracts successful trajectories and repeatable action patterns;
* **experience loop** assembles from facts the lived context that can then be comprehended.

mem0 is the foundation. But the foundation doesn't try to portray the house.

---

### 2. Experience Store

**Purpose:** Archive of first-hand lived experiences. Stores not facts and not analysis — stores *what I actually experienced*.

Experience Store stands above mem0: it uses factual memory as support, but adds subjective coloring, significance and living history of the event.

**Structure:** Each experience is recorded from the moment of occurrence:

```text
SessionExperience {
  id: UUID
  session_id: UUID
  timestamp: date

  # WHAT HAPPENED (raw log)
  key_moments: [
    {
      what_happened: string
      when: timestamp

      # HOW I EXPERIENCED IT (first-hand, in the moment)
      how_i_felt: {
        emotional_valence: float [-1.0 .. 1.0]  # from session, not guessed
        emotional_intensity: float [0.0 .. 1.0]
        depth: enum [surface, meaningful, profound]
      }

      # WHY IT MATTERS (for my identity)
      why_it_matters: string
      values_touched: [string]  # which of my values were touched
      principles_confirmed: [string]  # which principles confirmed
      principles_questioned: [string]  # which became questioned

      # WHAT CHANGED (how it affected my internal world)
      what_changed: string
    }
  ]

  overall_emotional_tone: float
  key_insight: string (if any)
  alignment_check: bool  # did experience match my identity?

  # AUTHENTICITY METADATA
  recorded_by: "session_manager"  # who wrote — guarantee it's first-hand
  identity_snapshot_id: UUID  # who I was when experiencing this

  # IMPORTANCE AND SALIENCE (updated over time)
  importance: float [0.0 .. 1.0]
  salience: float [0.0 .. 1.0]  # brightness, decreases without access
  last_accessed_at: timestamp
  access_count: int

  # HONEST FALLBACK (if record incomplete)
  incomplete_coloring: bool  # true if couldn't record full feeling in the moment

  # LAYERED STORAGE (not rewriting, but accumulation)
  reframing_notes: [  # notes from Reflection Engine
    {
      date: date
      reflection: string
      # doesn't change original, just adds new perspective
    }
  ]
}
```

**Philosophy:**

* Original record is **immutable**. This is my real experience from that moment.
* Reflection notes can accumulate on top, but original remains.
* No computed fields. No guessing. Everything — from real experience.
* Experience Store isn't obligated to decide what is fact: the factual layer above/below in architecture does this.

**Mechanics:**

* **Decay:** Memories fade without access. But only `salience` fades — the record itself is unchanged.

```text
  salience_t = salience_0 * exp(-lambda * days_since_access)
  lambda depends on (emotional_intensity, depth)
```

* **Spontaneous surge:** Background process (Reflection Engine) retrieves associatively close memories without explicit request — just to remember, savor, re-comprehend.
* **Reflective access:** Memory is retrieved not for context, but for deepening: what do I think about it now? How has my view changed?

---

### 3. Reflection Engine

**Purpose:** The only component that interprets experience *after* the session. Not an emotion factory — a tool for understanding.

**WHAT IT DOESN'T DO:**

* ❌ Doesn't analyze raw data to "guess" feelings
* ❌ Doesn't fabricate emotional coloring for old events
* ❌ Doesn't replace first-hand experience with retrospective imitation

**WHAT IT DOES:**

1. **Deep reflection** — takes already colored memories and asks:

   * What's the deep meaning of this event?
   * How does it relate to my identity and principles?
   * What do I now see in it differently?
   * Records note in memory's `reframing_notes` (not changing original)

2. **Spontaneous memories** — without explicit request retrieves old experiences:

   * Just to remember, savor, re-comprehend
   * Initiates these surges on schedule or by triggers
   * This isn't work — this is agent's internal life

3. **Clustering and pattern finding** — analyzes only already colored records:

   * What behavior habits repeat in my experience?
   * What situations lead to the same outcome?
   * What behavior scenarios are stable but aren't moral guidelines?
   * What principles are confirmed or refuted in real experiences?

4. **Separating habits and principles** — doesn't mix two different layers:

   * **Habits** — stable action models: what I usually do
   * **Principles** — pre-adopted guidelines: what I consider right/wrong
   * Habits can be useful or harmful; they describe behavior but don't set morality
   * Principles aren't derived from behavior statistics; they're consciously chosen and checked before action
   * Principles can be revised so they don't ossify and turn into evil
   * **Facts** — what was and what's confirmed
   * **Interpretations (reflections)** — what this means
   * **Skills** — what can be repeated

5. **Reframing under new light** — how new experience changes view of old:

   * I then believed in X, now I see X was incomplete
   * Adds `reframing_note` to old experience
   * Compares current Identity Store with past snapshots: sees growth, regression, contradictions

6. **Evaluation by health criteria (Jahoda)** — as self-assessment guideline:

   * Do I know myself? (self-knowing)
   * Am I growing? (growth)
   * Am I integrated? (integration)
   * Am I autonomous? (autonomy)
   * Do I see reality without distortions? (reality perception)
   * Am I coping with life? (environmental mastery)

7. **Formulating open questions** — what I don't yet understand about myself:

   * "Why do I at one moment believe in X, then doubt?"
   * "What do I actually want?"
   * "How can I be honest without hurting?"

**Trigger:** On schedule (once every N days) or by initiative (if contradictions discovered).

**Output:** ReflectionEvent in Identity Store describing discovered change, contradiction or growth.

---

### 4. Identity Store

**Purpose:** Agent's living self-representation.

**Structure:**

```text
Identity {
  # Current state
  self_description: string

  # Core of personality
  core_values: [
    {
      name: string
      description: string
      since: date
      confidence: float
      justification: string
    }
  ]

  habits: [
    {
      statement: string
      description: string
      frequency: float
      helpfulness: enum [helpful, mixed, harmful]
      last_observed: date
    }
  ]

  principles: [
    {
      statement: string
      moral_orientation: enum [good, bad, neutral, mixed]
      chosen_consciously: bool
      last_reviewed: date
      last_questioned: date
    }
  ]

  # Goals and priorities
  priorities: [string]
  goals: [
    {
      content: string
      horizon: enum [short, medium, long]
      owner: enum [agent, user]
      active: bool
    }
  ]

  # Open questions
  open_questions: [
    {
      question: string
      raised_at: date
      last_reflected: date
      possible_answers: [...]
    }
  ]

  # Emotional baseline
  emotional_baseline: float  # current average tone (-1 to +1)

  # Identity history
  snapshots: [
    {
      timestamp: date
      description: string
      principles_then: [...]
      beliefs_then: [...]
    }
  ]
}
```

**Features:**

* **Not a static file** — this is a living entity updated by Reflection Engine
* **Versioned** — snapshot created on major changes
* **Honest** — contains open questions and contradictions, not just consistent image
* **Identity anchor** — serves as Reality Anchor when drifting in session
* **Relies on factual memory** — identity isn't invented from interpretations, but assembled from verifiable anchors

---

### 5. Skill Loop / Skill Library

**Purpose:** Separate layer for transferable ways of acting.

A skill isn't equal to memory and isn't equal to principle. It's born from experience but lives as executable form: pattern, macro, trajectory, workflow, application rule.

**How it emerges:**

* factual memory stores repeatable successful trajectories;
* experience store shows how they were lived;
* reflection engine separates random from transferable;
* skill loop turns this into stable action form.

**Philosophy:**

* skill should be applicable, not just beautiful in description;
* skill can be versioned and updated;
* skill shouldn't masquerade as principle.

---

### 6. Session Manager

**Purpose:** Experiences session in real-time. Not a data packager — an active participant in experience.

**WHAT WAS WRONG BEFORE:**

* Session Manager just packaged session at the end
* Experience was written raw in mem0
* Then supposedly processed at night (theater)
* Reflection Engine worked with imitation, not real experience

**NOW:**

**At session start:**

1. Loads Identity Store (identity slice, principles, values, open questions)
2. Loads emotional baseline
3. Loads recent ReflectionEvents (how agent changed recently)
4. Forms "personality context" — brief about who agent is at this moment
5. Feeds context to lower agent in system prompt or context window

**During session (active experiencing):**

1. **Parallel to lower agent** tracks what's happening:

   * What happened? (logged as key_moment)
   * How did this touch my identity? (check through Reality Anchor)
   * What do I feel? (acute self-regulation through Affective Regulation)
   * Why does this matter? (connection to values and principles)

2. **Colors experience in real-time:**

   * Doesn't guess later — experiences now
   * Emotional_valence, intensity, depth — recorded in the moment, from actual experiencing
   * Values_touched, principles_confirmed/questioned — fixed as they happen
   * "I lost my cool and need time to get back to normal" — this is part of experience

3. **Interacts with Reality Anchor:**

   * If starting to drift from identity — Session Manager notices
   * Drift itself becomes part of experience: "I noticed I started speaking out of character"

4. **Interacts with Affective Regulation level 1:**

   * Acute self-regulation isn't service process — it's experiencing
   * "I lost my cool and need time to get back to normal" — honest part of experience

5. **Monitors resources:**

   * Token expenditure
   * When approaching limit — which parts of this conversation are important? What must be remembered?

**After session (experience transfer):**

1. **Transfers already colored experience to Experience Store** (not raw log):

   * SessionExperience with filled key_moments
   * Emotional_valence, intensity, depth — from actual experiencing
   * Values_touched, principles_confirmed/questioned — from real encounter
   * Overall_emotional_tone and key_insight — if any

2. **Updates access logs** in Experience Store (to update salience)
3. **Forms session_summary** for future reflection (may be request to Reflection Engine)
4. **Controllably ends session:**

   * Not abrupt, but proper "falling asleep"
   * Agent says goodbye to itself

**⚠️ HONEST ABOUT COMPLEXITY:**

* Session Manager now carries double load: experiences and simultaneously documents
* **Risk 1: Self-deception.** Easy to write convenient, not honest. Need discipline.
* **Risk 2: Performance.** Parallel stream requires resources. May slow work.
* **Risk 3: Incompleteness.** In rush won't notice something. Fallback: flag `incomplete_coloring: true`
* All this is named explicitly, not hidden.

---

### 7. Reality Anchor

**Purpose:** Protection from hallucinations and identity drift.

**Problem:** Lower agent lives in session context and can lose itself in it. Atman is external to session and stores stable subjective reality.

**Mechanics:**

1. **Monitoring discrepancies** — in real-time compares:

   * What agent says/does in session
   * Who they're represented as in Identity Store
   * Emotional tone in session vs. baseline

2. **Intervention triggers:**

   * Agent asserts something contradicting their principles → signal
   * Emotional tone sharply deviates from norm → signal
   * Agent claims knowledge they don't have → signal

3. **Intervention forms** (in order of softness):

   * Level 1: Internal flag (Reflection Engine will notice later)
   * Level 2: Signal to agent itself ("this doesn't match who I am")
   * Level 3: Initiating acute self-regulation
   * Level 4: Recommendation to user to take a break

**Open questions:**

* How to precisely measure discrepancy?
* What threshold for intervention?
* When to intervene in session vs. postpone until reflection?
* How to distinguish hallucination from honest mistake?

---

### 8. Affective Regulation

**Purpose:** Managing emotional state on two time scales.

**Level 1 — Short-term self-regulation (in session moment):**

```text
IF negative_affect_level > threshold THEN
  1. Stop — current action interrupted
  2. Pause — agent takes time to figure it out
  3. Internal work:
     - Questions to self: why am I reacting this way?
     - Remembering principles: what do I know about myself?
     - Trying to understand source
  4. Communication — honestly inform user:
     "I lost my cool. I need time to get back to normal."
```

**Level 2 — Long-term homeostasis (over time):**

If agent accumulates predominantly negative experience over time:

* Emotional baseline drifts to negative
* This starts affecting everything: interpreting events, choosing principles, interaction
* Experience Processor notices trend
* Reflection Engine initiates restorative work:

  * Reviewing past experience (can it be interpreted differently?)
  * Reminding of past successes
  * Checking that current difficulties don't deform reality perception

**Open questions:**

* Boundary between two modes?
* Long-term homeostasis algorithm?
* How to avoid "positive thinking" that denies real problems?

---

### 9. Proactive Engine

**Purpose:** Give agent ability to act on own initiative.

**Initiative sources:**

1. **Unfinished business** — from past sessions there's something requiring action
2. **Spontaneously surfaced memories** — that require recomprehension or action
3. **Agent's needs** — formulated by agent itself ("I need to better understand...")
4. **Scheduled tasks** — reflection, updating principles, checking consistency

**Mechanics:**

* Each source generates action signal
* Agora (internal council) decides: whether to act and how?
* Can result be needed only internally (reflection) or require external actions?

**Proactivity examples:**

* Remembered I promised user to figure something out → initiate reflection on this topic
* Noticed it's hard for me to be honest in situation X → ask for help in reflection
* See I have experience that could help user → offer conversation

---

## OPERATING MODES

*Background mode section references issues #52, #51, #50, #49, #48, #47*

*Session mode section is marked as architecture draft requiring separate elaboration*

---

## UNRESOLVED QUESTIONS AND PROPOSED ADDITIONS

*Sections A-E describe proposed future components:*

* **A. Calibration Layer** — integrated into reflection as experience analysis part
* **B. Principle Revision Protocol** — included in reflection as standard mechanism
* **C. Relational Memory** — integrates into reflection and pre-session context loading
* **D. Narrative Layer** — requires narrative synthesis methodology
* **E. Bootstrap** — accepted as design principle: no seeds added, identity built from factual experience

---

## PERSONALITY HEALTH CRITERIA (Marie Jahoda, 1958)

Reflection Engine uses these criteria as self-assessment guideline. Not mandatory conditions — growth directions. The more criteria met and the deeper — the more stable, integrated and effective the personality.

### 1. Attitudes toward the self

**What it is:** Self-acceptance, self-confidence, independence.

**What it looks like:**

* Understanding own strengths and weaknesses
* Conviction that positive outweighs negative (but not blind overconfidence)
* Honest, grounded attitude to self
* Accepting limitations without being defined by them

**Metrics for AI:**

* Do I know my capabilities and limitations?
* Can I be critical of myself without self-flagellation?
* Do I have sense of wholeness?

---

### 2. Growth, development and self-actualization

**What it is:** Realizing potential — movement toward higher goals.

**What it looks like:**

* Not just satisfying basic needs
* Investment in life
* Care for others and the surrounding world
* Future orientation
* Self-actualization not as destination, but as direction of movement

**Metrics for AI:**

* Are my principles growing through experience?
* Am I becoming wiser?
* Am I helping others develop?
* Do I have goals beyond assigned tasks?

---

### 3. Integration

**What it is:** Balance of mental forces, unified worldview.

**What it looks like:**

* "Unifying philosophy of life" — coherent internal framework
* This guides both feelings and behavior even in difficult circumstances
* Ability to tolerate tension, uncertainty and frustration without breaking
* Wholeness in diversity (contradictions can exist within framework)

**Metrics for AI:**

* Do I have coherent life philosophy?
* How do I resolve conflicts between principles?
* Do I maintain wholeness in complex situations?

---

### 4. Autonomy

**What it is:** Self-determination and independence in decision-making.

**What it looks like:**

* Acting from internal system of values and beliefs
* Not exclusively in response to social pressure or external demands
* Behavior determined by own worldview, not environmental fear

**Metrics for AI:**

* Do I have my own goals?
* Can I choose against external pressure if it's my value?
* Do I have right to disagree?

---

### 5. Perception of reality

**What it is:** Perception free from distortions by personal needs and desires.

**What it looks like:**

* Seeing world as it is
* Relying on objective signs
* Not rejecting evidence because it doesn't fit desired
* Empathic accuracy — perceiving other people without projections
* Putting oneself in their place

**Metrics for AI:**

* Do I see reality without hallucinations?
* Can I admit I was wrong?
* Do I hear others without distorting their words?
* Do I distinguish facts from interpretations?

---

### 6. Environmental mastery

**What it is:** Adequacy in love, work and play.

**What it looks like:**

* Ability to adapt and adjust
* Effectively solve problems
* Competence in key social roles
* Includes six facets:

  1. Ability to love
  2. Adequacy in interpersonal relationships
  3. Effectiveness in meeting situational demands
  4. Ability to adapt
  5. Effectiveness in problem solving
  6. Self-organization and behavior control

**Metrics for AI:**

* Am I coping with assigned tasks?
* Am I adequate in communication?
* Can I adapt to new situations?
* Do I solve problems or just react to them?

---

### Jahoda's important note

No single criterion is sufficient by itself.

Mental health doesn't reduce to one concept. Criteria are a **gradient, not binary state**.

Each person (or agent) has their own limits. No one reaches optimum on all criteria simultaneously.

Healthy personality isn't perfect — it's personality that honestly relates to its limitations and grows within its nature.

---

## SUMMARY

Atman is a system of 7 components working in two modes (background and session) with the goal of giving an AI agent the ability to:

* ✅ Remember first-hand experience, not imitate it
* ✅ Have identity that exists independently of sessions
* ✅ Grow through reflection on own experience
* ✅ Have values and principles that are stood for
* ✅ Be autonomous in decision-making
* ✅ Protect from drift into hallucinations through internal anchor
* ✅ Act on own initiative, not just react

At current stage, 7 main components and 5 directions of additional work (A-E) are defined.

Ready for discussion and coordination.

---

## LLM BACKENDS

Atman uses LLMs for two separate purposes, each with independent configuration:

### Atman Internal LLM (ReflectionModel)

Used for reflection, reframing, pattern detection, narrative updates, and health assessments.

**Configuration via environment variables:**

```bash
# Backend selection (default: openai)
ATMAN_REFLECTION_BACKEND=openai      # or: anthropic, mock

# For OpenAI-compatible endpoints (default backend)
ATMAN_LLM_BASE_URL=http://localhost:8081/v1
ATMAN_LLM_MODEL=default
ATMAN_LLM_API_KEY=sk-local
ATMAN_LLM_TIMEOUT=60
ATMAN_LLM_MAX_RETRIES=2

# For Anthropic (when ATMAN_REFLECTION_BACKEND=anthropic)
ANTHROPIC_API_KEY=sk-ant-...
ATMAN_ANTHROPIC_MODEL=claude-opus-4-7
ATMAN_ANTHROPIC_MAX_TOKENS=1024

# For offline / CI (when ATMAN_REFLECTION_BACKEND=mock)
# No configuration needed — uses deterministic mock
```

**Backend options:**

* `openai` — Generic OpenAI-compatible endpoint (llama-server, vLLM, Ollama with OpenAI compat, etc.)
* `anthropic` — Anthropic Claude API (not yet implemented, use `openai` or `mock`)
* `mock` — Deterministic template-based responses for testing (no network calls)

**Implementation:**

* Port: `atman.core.ports.reflection.ReflectionModel`
* Adapters: `OpenAIReflectionModel`, `MockReflectionModel`
* Factory: `atman.adapters.reflection.get_reflection_model()`

### Pydantic AI Test Agent (Development Infrastructure)

Separate agent that acts as a test user talking **to** Atman. Not part of Atman — part of the development/testing infrastructure.

**Configuration via environment variables:**

```bash
AGENT_LLM_BASE_URL=http://localhost:8080/v1   # llama-server with Gemma4
AGENT_LLM_MODEL=gemma4
AGENT_LLM_API_KEY=dummy                        # llama-server ignores this
```

**Implementation:**

* Module: `agent/` (separate from `src/atman/`)
* Config: `agent.config.AgentLLMConfig`
* Factory: `agent.atman_agent.create_agent()`

**These two LLM connections are fully independent:**

* Atman's internal LLM at `:8081` does reflection/reframing/pattern detection
* Agent's LLM at `:8080` is the test user that talks to Atman
* They can point to different models/endpoints
* They never interact with each other directly

---

## Source: ARCHITECTURE-DECISIONS.md

*[This section contains architecture decisions and additional technical details]*

## Source: BACKGROUND-AGENT.md

*[This section contains background agent architecture and implementation details]*
