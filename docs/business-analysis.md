# Business Analysis: Post-Sales Shipment Monitoring

> This analysis summarizes an operational field study conducted at a Vietnamese freight forwarder
> handling full-container-load (FCL) ocean freight. Figures and observations reflect field interviews,
> direct process observation, and timed measurements. Company financials, headcount, and individual
> identities are withheld.

## 1. Operational Context

Freight forwarders operate in a low-margin market where freight rates between competing providers
frequently converge. Customer retention after contract signing depends on the speed, accuracy, and
proactivity of post-sales shipment updates.

This study examined the post-sales workflow for ocean import shipments (Incoterms groups E and F)
and export shipments (Incoterms groups C and D) managed by the commercial division. Under E and F
terms, the forwarder manages the main carriage; the buyer bears the risk and requires continuous
visibility to plan customs clearance, warehouse labor, and inland haulage.

## 2. Baseline Process and Operational Cost

A field survey of frontline sales and customer service staff measured the following operational baseline:

- **Workload:** Each sales representative actively monitors 20 to 30 concurrent shipments.
- **Inquiry volume:** Each representative handles 70 to 150 customer inquiries per month, translating to 10 to 20 manual lookups per day.
- **Lookup duration:** Answering a single shipment inquiry takes 15 to 30 minutes, measured by stopwatch across four to five fragmented sources.
- **Reactive ratio:** Approximately 9 out of 10 customer inquiries arrive before the representative sends an update. Staff learn of carrier schedule changes 2 to 4 hours after publication.
- **First-contact resolution:** Only about 10% of customer questions receive an immediate answer; 90% require a callback after manual investigation.
- **Onboarding overhead:** New representatives require 3 to 6 months to handle an ocean import shipment independently, driven by uncodified operating practices.

## 3. Root Causes

Process mapping identified four primary operational bottlenecks:

- **Fragmented data sources (PP-2):** Existing Transport Management Systems (TMS) manage billing and dispatch; Customer Relationship Management (CRM) tools record customer records. Neither system tracks live vessel positions at sea. Representatives manually combine carrier portals, public AIS tracking websites, internal spreadsheets, and email threads.
- **Reactive communication (PP-1):** Because no unified screen displays live voyage status, representatives only investigate when a customer asks. When carrier schedules shift, the customer frequently notices before the forwarder.
- **Late anomaly detection (PP-3):** Schedule slips, carrier rollovers, and destination port congestion are identified hours or days after occurrence, eliminating lead time to adjust inland logistics or file demurrage waivers.
- **Uncodified operational knowledge (PP-4):** Vessel identification rules, carrier-specific tracking quirks, and tidal draft constraints reside entirely in the memory of senior staff rather than system logic.

## 4. Proposed Solution: The Add-On Layer

The proposed solution introduces a lightweight monitoring layer beside the existing TMS and CRM:

- **Explicit boundary:** Does not replace the TMS, CRM, or carrier operational systems.
- **Data aggregation:** Collects live vessel AIS positions, port weather forecasts, and tidal window calculations into one operational view.
- **Rule-based calculations:** Recomputes ETAs dynamically with transparent kinematics and environmental adjustment factors rather than opaque models.
- **Controlled automation:** Parses carrier emails for schedule and rollover notices, generating reviewable proposals that require human approval before applying changes.

## 5. Expected Business Outcomes

Target improvements based on the identified bottlenecks:

- Reduce shipment lookup time from 15–30 minutes to under 1 minute through a unified single-screen view.
- Shift the proactive-to-reactive communication ratio from 10:90 to 80:20 by alerting staff when ETA variance exceeds operational thresholds.
- Detect carrier schedule slips and rollovers within 10 minutes of email receipt rather than 2–4 hours.
- Protect customers from avoidable demurrage and detention charges by surfacing arrival delays before the free-time window begins.

## 6. Scope Boundaries

The working prototype validates technical feasibility within defined boundaries:

- Monitors 3 to 5 concurrent shipments across two short-sea regional routes (Singapore / Hong Kong / Kaohsiung to Cát Lái Port, and the reverse export leg).
- Uses rule-based kinematics and verified weather inputs; does not train machine-learning prediction models.
- Uses terrestrial AIS coverage; does not license satellite AIS feeds.
- Relies on structured carrier email ingestion and public tracking endpoints; does not build direct EDI (IFTSTA/IFTSAI) integrations.
