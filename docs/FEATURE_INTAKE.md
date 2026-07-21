# Feature Intake

Every implementation prompt enters the intake gate before code changes. A new
project spec also enters through this gate before it becomes product docs,
stories, or implementation work.

The human does not need to classify risk. The harness does.

## Intake Flow

```text
Resolve input
    |
    v
Classify work type
    |
    v
Restate as a work item
    |
    v
Find affected product docs and stories
    |
    v
Run the risk checklist
    |
    v
Choose lane: tiny, normal, or high-risk
    |
    v
Create / update artifacts -> intake note
```

## Step 1: Resolve Input

Resolve the work source in this strict priority order. Use the first that
exists; do not merge sources unless asked.

1. `change_request.md` (repo root)
2. `idea.md` (repo root)
3. `my_idea.md` (repo root)
4. the explicit user prompt in the conversation

Record which source was used — it goes in the intake note.

## Step 2: Classify Work Type

| Type | Use when | Typical artifact |
| --- | --- | --- |
| New initiative | A larger product area that needs multiple stories | Initiative notes + story packets |
| New spec | A user-provided spec must become harness-ready docs | Product docs, candidate epics, decisions |
| Spec slice | Implementing a selected behavior from an accepted spec | Story packet |
| Change request | Changing, fixing, or refining accepted behavior | Story packet or direct patch |
| Bug investigation | Diagnosing unexpected or broken behavior | Investigation notes, then story or patch |
| Maintenance | Dependency, operational, performance, or technical change | Story packet, validation report, or decision |
| Harness improvement | Improving how humans and agents collaborate | Docs/template update |

## Step 3: Restate as a Work Item

One actionable sentence: what behavior must become true, and for whom.

## Step 4: Find Affected Docs

Locate affected `docs/product/*` and `docs/stories/*`. For architecture- or
boundary-touching work, read `docs/ARCHITECTURE.md`. For durable-rule changes,
scan `docs/decisions/*`. Read the smallest section that answers the current
question.

## Step 5: Run the Risk Checklist

Mark every flag that applies. Flag count and hard gates drive the lane.

| Risk flag | Applies when the work touches |
| --- | --- |
| auth | login, logout, sessions, JWT, password, refresh token |
| authorization | roles, permissions, tenant or company scope |
| data model | schema, migrations, uniqueness, deletion, retention |
| migration / data loss | data migration, backfill, or destructive change |
| audit / security | audit logs, privacy, sensitive data, access logs |
| external systems | email, payments, cloud services, provider SDKs, queues, webhooks |
| public API / contract | API shape, response envelope, client-visible behavior |
| existing behavior change | already implemented or test-covered behavior changes |
| weak proof | unclear or missing tests around the affected area |
| multi-domain | more than one product domain changes at once |

## Step 6: Choose the Lane

```text
0-1 flags     -> tiny or normal, based on code impact
2-3 flags     -> normal with stronger validation
4+ flags      -> high-risk
any hard gate -> high-risk unless the human explicitly narrows scope
```

**Hard gates** (any one forces high-risk): auth, authorization, data loss or
migration, audit/security, external provider behavior, removing or weakening
validation.

### Lane requirements

- **Tiny** — low-risk docs, copy, names, or narrow edits. Patch directly, keep
  affected docs current, run available quick checks.
- **Normal** — story-sized behavior with bounded blast radius. Create a story
  packet, link product docs, add/update validation expectations, implement the
  smallest vertical slice.
- **High-risk** — work affecting security, data, scope, contracts, or multiple
  domains. Use the expanded story (overview, design, exec plan, validation), ask
  for human confirmation when direction is ambiguous, and record a durable
  decision.

## Step 7: Output

Always write an intake note at `docs/intake/<YYYY-MM-DD>-<slug>.md` using
`docs/templates/intake-report.md`. Add a story packet, matrix rows, or decision
record only when the work needs them.

Date format: `YYYY-MM-DD`. Slug: short kebab-case summary of the work.

## Boundaries

- Intake classifies and documents. It does not implement.
- Intake never edits application source code.
- If the harness docs are missing, run `/harness-setup` first.
