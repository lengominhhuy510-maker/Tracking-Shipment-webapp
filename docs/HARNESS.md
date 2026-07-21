# Harness

Harness is a lightweight, agent-ready workspace layer. It does not change what
your app does — it changes how agents and humans approach work on it. The app is
what users touch. The harness is what agents touch.

The goal: every change passes through intake, gets the right amount of structure
for its risk, and leaves behind honest proof and a clear record.

## Core Workflow

```text
intake  ->  story  ->  implement  ->  validate
```

1. **Intake.** Classify the work (type + risk lane) before touching code. See
   `docs/FEATURE_INTAKE.md` or run `/harness-intake`. Always produces an intake
   note.
2. **Story.** For story-sized work, write a story packet from
   `docs/templates/story.md` (or the high-risk variant for risky work).
3. **Implement.** Build the smallest vertical slice that satisfies the story's
   acceptance criteria. Stay inside the chosen risk lane.
4. **Validate.** Update `docs/TEST_MATRIX.md` with expected proof and record
   results honestly. Never claim a check passed unless it was actually run.

Every task can leave two kinds of output:

- **Product delta** — app code, tests, API, data model, or product docs.
- **Harness delta** — docs, templates, matrix rows, or decision records that make
  the next task easier.

## Key Files

| File / dir | Purpose |
| --- | --- |
| `AGENTS.md` | Agent entrypoint: behavioral rules and project context. |
| `docs/FEATURE_INTAKE.md` | How to classify and scope new work. |
| `docs/ARCHITECTURE.md` | System components, data flow, constraints. |
| `docs/stories/` | Story packets — one per story-sized unit of work. |
| `docs/decisions/` | Durable decision records. |
| `docs/TEST_MATRIX.md` | Maps product behavior to required proof. |
| `docs/product/` | Product context (PRD, roadmap, research). |
| `docs/templates/` | Templates for stories, decisions, validation, intake. |

## When to Run Intake

Run intake (`/harness-intake`) at the start of **any** new piece of work:

- A change request, idea, or spec arrives.
- A bug needs investigation.
- A maintenance or dependency change is requested.
- Anything that will change behavior.

Intake classifies the work, runs the risk checklist, picks a lane, and writes an
intake note under `docs/intake/`. It does not implement the work.

## When to Create a Story Packet

Create a story packet (`docs/templates/story.md`) when the work is more than a
tiny edit — i.e. it has acceptance criteria, bounded blast radius, and needs
proof. Tiny doc/copy/name edits do not need a story. High-risk work uses an
expanded story (overview, design, exec plan, validation) instead of a single
file.

## When to Create a Decision Record

Create a decision record (`docs/templates/decision.md` under `docs/decisions/`)
when a durable choice is made that future work should inherit — changes to
behavior, architecture, authorization, data ownership, API shape, audit/security,
or validation requirements. A note buried in a story or trace is **not** a
durable decision record; write the dedicated file.
