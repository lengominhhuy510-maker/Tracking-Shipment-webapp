# Real-Time Ocean Shipment Monitoring System

A post-sales tracking add-on for container freight forwarders that converts reactive customer inquiry handling into proactive delay detection.

[Bản tiếng Việt](README.vi.md) · [Business Analysis](docs/business-analysis.md) · [Architecture](docs/ARCHITECTURE.md) · [Engineering Process](docs/ENGINEERING-PROCESS.md) · [Decisions](docs/decisions/)

## Screenshots

| Customer journey | System architecture |
|---|---|
| <img src="docs/screenshots/process-customer-journey.png" width="420" alt="Customer journey map for an FCL shipment"> | <img src="docs/screenshots/architecture-layers.svg" width="420" alt="System architecture overview"> |

[![View system walkthrough](https://img.shields.io/badge/%E2%96%B6_View_system_walkthrough-2563EB?style=for-the-badge)](docs/GALLERY.md)

## The Problem

- Frontline sales representatives monitor 20 to 30 concurrent FCL shipments across four to five fragmented sources, spending 15 to 30 minutes on every customer inquiry.
- Approximately 90% of customer inquiries arrive before staff send an update, leaving forwarders in a reactive customer service posture.
- Forwarders learn of carrier schedule changes 2 to 4 hours after publication, eliminating lead time to adjust inland haulage or warehouse labor.
- Actual arrival drifts from the estimated arrival time for reasons the current process never surfaces: a carrier rollover or transit change, heavy weather along the route, and wind, sea state, or tidal water level at the destination port that slows the approach.
- Operational knowledge about carrier tracking quirks and vessel identifiers resides with individual staff rather than system logic.

## What the System Does

- Centralizes ocean container tracking into a single view showing live vessel position, voyage milestones, and environmental conditions.
- Replaces manual carrier website checks with an automated baseline ETA fetch during shipment onboarding.
- Recomputes arrival ETAs dynamically using live AIS vessel positions, wind speed, surface currents, and port tidal windows.
- Ingests carrier notice emails to identify vessel rollovers and schedule revisions automatically.
- Generates reviewable update proposals for staff approval, protecting operational records from untrusted input.
- Notifies cargo owners proactively before estimated arrival variance exceeds acceptable operational thresholds.

## How It Works

The system operates as an add-on layer beside existing Transport Management Systems (TMS) and Customer Relationship Management (CRM) tools. It does not replace core transactional systems.

```text
Shipment Intake (B/L, Container, Incoterm, Vessel / Voyage)
   │
   ├──> Onboarding: IMO Resolver (Playwright) + Carrier ETA Agent (Playwright MCP)
   │
   ├──> Live Tracking: AIS Worker (aisstream.io WebSocket) + Weather/Tide Poller
   │
   ├──> ETA Engine: 2-Tier Rule-Based (Kinematics + Wind / Current / Tide Adjustment)
   │
   ├──> Reasoning: Agent A (AG2) generates qualitative operational assessment
   │
   └──> Inbound Email: IMAP Poller + LLM Extraction ──> Human-in-the-Loop Proposal ──> Staff Approval
```

Arrival ETAs derive from a two-tier rule-based engine rather than machine-learning prediction models. Tier 1 applies kinematic distance-speed calculations along the verified voyage path. Tier 2 applies empirical adjustment factors for headwind, adverse surface currents, and destination tidal draft constraints. Large Language Models (LLM) coordinate external tools and summarize qualitative assessments; they do not calculate quantitative baseline ETAs.

## Human-in-the-Loop Safeguards

- Inbound carrier emails represent untrusted input; the email agent never updates shipment records or active legs automatically.
- Extracted schedule changes and vessel rollover notices create structured records in `agent_proposals`.
- Frontline staff review and approve or reject proposals through a dedicated interface before changes take effect.
- Proposal approval updates active leg records, triggers AIS re-subscription, and appends an entry to the audit log (`eta_history`).
- Automated notification forwarding routes only to pre-configured internal allowlists defined in server environment variables.

## What Was Built

- Designed and implemented 10 relational models with forward-only Alembic migrations and idempotent database seeding.
- Authored 39 backend test suites and frontend component tests verifying offline deterministic behavior.
- Packaged 5 containerized services: FastAPI backend, Playwright MCP scraper, PostgreSQL 16, Redis 7, and Caddy reverse proxy with automatic TLS.
- Validated end-to-end voyage tracking on two regional short-sea demo routes connecting Singapore, Hong Kong, Kaohsiung, and Cát Lái Port.
- Handled four structured email extraction outcomes: `proposals_created`, `no_match`, `rejected_allowlist`, and `parse_failed`.
- Maintained a clean architectural boundary where Node never connects to PostgreSQL and Python never connects to Redis.

## Engineering Decisions

- Ran one Uvicorn worker with embedded lifespan tasks ([ADR 0003](docs/decisions/0003-single-process-embedded-workers.md)) — keeps in-memory state consistent and avoids external queue overhead at demo scale.
- Enforced a single `.env` file loaded via Pydantic Settings with no fallback chain ([ADR 0001](docs/decisions/0001-config-single-source-env.md)) — eliminates configuration ambiguity and prevents credential leaks.
- Separated Python and Node service boundaries ([ADR 0002](docs/decisions/0002-language-boundary-python-node.md)) — scraper runs isolated in Node; database access remains exclusive to Python.
- Standardized database schemas on text columns with check constraints and UTC timestamps ([ADR 0004](docs/decisions/0004-db-conventions-enum-text-check-utc.md)) — avoids migration drift across environments.
- Applied a three-part integration boundary ([ADR 0005](docs/decisions/0005-integration-boundary-option-1-5.md)) — maps third-party payloads into typed Pydantic models with unified error classification.
- Pinned experimental dependencies exactly ([ADR 0006](docs/decisions/0006-dependency-pinning-lock-reproducibility.md)) — verified compatibility in an initial spike before feature implementation.

## Role and Contribution

Student team lead for the enterprise practicum project:

- Selected the analysis topic and defined the problem scope with the business department.
- Split work across the team and reviewed deliverables.
- Owned the codebase and wrote the technical specification and interface contract.
- Applied AI automation to manage AI-assisted development: task decomposition, per-task verification, and scope control.

## Run It Locally

### Prerequisites

- Docker Desktop and Docker Compose
- Node.js 20+ (for local frontend development)
- Python 3.12+ (for local backend development)

### Quick Start with Docker

```bash
# 1. Clone repository
git clone https://github.com/lengominhhuy510-maker/Tracking-Shipment-webapp.git
cd Tracking-Shipment-webapp

# 2. Configure environment from template
cp .env.devtest2 .env

# 3. Launch full stack (exposing port 1476 for local OAuth redirects)
docker compose -f infra/docker-compose.yml -f infra/docker-compose.dev.yml up -d --build

# 4. Load demo data (4 shipments, 2 users)
docker compose -f infra/docker-compose.yml exec webapp python -m app.db.seed

# 5. Open browser at http://localhost:1476
```

### Run Tests

```bash
# Backend test suite (39 test files, offline deterministic)
cd backend && pytest

# Frontend test suite
cd frontend && npm test
```

## Documentation

- [System Walkthrough](docs/GALLERY.md) — architecture, process analysis, and every application screen.
- [Detailed Business Analysis](docs/business-analysis.md) — process study, time measurements, and cost baseline.
- [Architecture Overview](docs/ARCHITECTURE.md) — 4-layer structure, component boundaries, and data flows.
- [Technical Specification](Spec_Demo_GiamSatLoHang-v0_9_19.md) — complete functional specification (Vietnamese).
- [Interface Contract](Interface-Contract_v0.9.9.md) — API endpoints, database schemas, and environment variables.
- [Engineering Process](docs/ENGINEERING-PROCESS.md) — delivery methodology, story packets, and testing discipline.
- [Architecture Decisions](docs/decisions/) — six formal Architecture Decision Records.

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
