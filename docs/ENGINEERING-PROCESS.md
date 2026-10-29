# Engineering Process and Governance

This document describes the engineering process, architecture governance, and validation discipline
used to build the shipment monitoring prototype.

## 1. Process Framework

Every code change followed a four-stage delivery pipeline:

```text
Intake  ──>  Story Packet  ──>  Implementation  ──>  Validation Matrix
```

- **Intake:** Classified the requested change by work type (feature, fix, maintenance, spike) and risk lane (tiny, medium, high-risk). High-risk work touched external integrations, data models, or security boundaries.
- **Story packet:** Scoped the vertical slice before writing code. High-risk work required four formal sections: overview, design, execution plan, and validation.
- **Implementation:** Built the smallest vertical slice satisfying the acceptance criteria. Followed test-driven development (TDD) for business rules and integration boundaries.
- **Validation:** Added a corresponding row to `docs/TEST_MATRIX.md`. Recorded results only after real command execution; never marked a check passed based on expectation alone.

## 2. Story Packets (`docs/stories/`)

Story packets served as bounded contracts for implementation units:

| Story Packet | Focus | Risk Lane | Primary Outcome |
|---|---|---|---|
| `TASK-02` | Database schema & migrations | High-risk | 10 models, forward-only Alembic migration, idempotent seed. |
| `TASK-07` | Weather, tide, port geocode | High-risk | External provider polling, WPI geocoding, cache fallback on error. |
| `TASK-10` | Scraper service infra | High-risk | Playwright MCP, BullMQ, Redis isolation (no database URL in Node). |
| `TASK-11` | IMO resolver & leg linking | High-risk | Vessel name to IMO resolution, single-transaction leg mirror. |
| `TASK-12` | Carrier ETA agent | High-risk | Agentic browser navigation, non-blocking fallback if scrape fails. |
| `TASK-13` | Inbound email agent | High-risk | IMAP poller, double allowlist, human-in-the-loop proposals. |
| `TASK-14` | Authentication & authorization | High-risk | OAuth OIDC (Google/Azure), session JWT, route and WebSocket guards. |
| `TASK-16` | Auto-forward service | High-risk | Proposal notification to allowlisted recipients, four-field audit log. |

Template definitions reside in `docs/templates/story.md`.

## 3. Architecture Decision Records (`docs/decisions/`)

Durable design choices were recorded as numbered ADRs to capture context, alternatives considered,
and consequences before code was merged:

- **[ADR 0001](decisions/0001-config-single-source-env.md):** Enforced a single `.env` file loaded via Pydantic Settings with no fallback chain, preventing secret leaks and configuration ambiguity.
- **[ADR 0002](decisions/0002-language-boundary-python-node.md):** Isolated language boundaries so Node never touched Postgres and Python never touched Redis.
- **[ADR 0003](decisions/0003-single-process-embedded-workers.md):** Ran one Uvicorn worker with embedded lifespan tasks, keeping in-memory state consistent without external queue overhead.
- **[ADR 0004](decisions/0004-db-conventions-enum-text-check-utc.md):** Standardized database conventions on text columns with check constraints, UTC timestamps with timezone, and forward-only migrations.
- **[ADR 0005](decisions/0005-integration-boundary-option-1-5.md):** Standardized external integrations on three parts (internal typed model, small client, unified error mapping) without speculative interfaces.
- **[ADR 0006](decisions/0006-dependency-pinning-lock-reproducibility.md):** Pinned experimental dependencies exactly and validated compatibility in an initial spike before feature development.

## 4. Test Matrix and Proof Discipline (`docs/TEST_MATRIX.md`)

Verification mapped directly to `docs/TEST_MATRIX.md` with explicit evidence tiers:

- **Unit proof:** Pure business logic, normalization rules, and kinematic calculations.
- **Integration proof:** Database constraints, error envelopes, provider fallbacks, and transactional boundaries.
- **End-to-end proof:** Complete offline demonstration covering vessel onboarding, AIS position updates, ETA recalculation, and proposal review in one deterministic test (`test_e2e_demo.py`).
- **Platform proof:** Multi-service container health checks, Caddy TLS reverse proxy, and SPA routing fallbacks.
- **Rule of honesty:** A row remained in `planned` status until tests or runtime logs demonstrated the claim. Key-gated tests (requiring live paid APIs) were marked structurally verified rather than claimed as executed.
