# Taalmel Sync — Backend

Event-sourced medication reality and follow-through backend, implementing
the architecture from the Taalmel Health design document (v4).

Core loop: **Prescribed → Observed → Reconciled → Why → Action → Resolved**

## Quick start

```bash
npm install
cp .env.example .env
npm run seed     # walks through the exact Section 14 demo flow, prints the doctor export
npm start        # starts the API on http://localhost:4000
```

Health check: `GET /health`

## Why this structure

The design doc's central claim is that the *value* isn't in structuring
prescription data — it's in reconciling multiple evidence sources,
figuring out *why* a gap exists, and tracking that to resolution
(Section 1's RCT finding). The code is organized to make that claim
literally true of the architecture, not just the pitch:

```
src/
├── events/              Section 5 — the append-only event log & its vocabulary
│   ├── eventTypes.js       canonical event types + evidence dimensions
│   └── eventStore.js       the ONLY write path into `events`
├── engines/              deterministic logic (Section 10: "consistency and
│   │                      safety matter more than generative flexibility")
│   ├── medicationStateEngine.js   derives 4 evidence dimensions (Section 6/7)
│   ├── conflictDetection.js       Section 8 — detects, never auto-resolves
│   ├── reasonClassification.js    Section 9.5 — 7-category taxonomy as data
│   ├── caseLifecycle.js           Section 9.9 — case as a tracked object
│   └── triggerEngine.js           Section 4 — the named trigger list
├── services/
│   ├── doctorExportService.js     Section 9.10 / 9.14
│   ├── auditTrailService.js       Section 9.7 / 9.8 — history + explainability
│   ├── safetyRulesService.js      Section 9.6 — NOT_COVERED over implied SAFE
│   ├── affordabilityService.js    Section 9.5 — named static sources only
│   ├── normalizationService.js    Section 9.1 — brand -> generic
│   └── ocrService.js              Section 10 — stubbed, same interface as a real model
├── routes/                HTTP layer — thin, delegates to engines/services
├── data/                   curated demo datasets (safety interactions, affordability)
└── db/
    ├── schema.sql          event-sourced schema; nothing is UPDATEd except case status
    └── seed.js             runs the exact Section 14 demo flow end-to-end

future-work/                explicitly out-of-scope items, documented with why
  minor-symptom-guidance/     Section 9.14 — architecture-only, no clinical content
  offline-sync/
  patient-wellness-timeline/
```

## What's implemented vs. stubbed

| Area | Status |
|---|---|
| Event-sourced data model (Section 5) | Fully implemented |
| 4-dimension evidence model + freshness (Sections 6/7) | Fully implemented |
| Conflict detection workflow (Section 8) | Fully implemented |
| 7-category reason classification (Section 9.5) | Fully implemented |
| Case lifecycle / resolution tracking (Section 9.9) | Fully implemented |
| Trigger engine (Section 4) | Fully implemented |
| Audit trail & provenance (Sections 9.7/9.8) | Fully implemented |
| Doctor export & minimal info card (Sections 9.10/9.14) | Fully implemented |
| Visit-to-visit companion loop (Section 9.13) | Fully implemented |
| Safety rules layer (Section 9.6) | Implemented against a small curated demo dataset only — see `src/data/safety-interactions.json`'s disclaimer |
| OCR extraction (Section 10) | Stubbed — same interface a real vision-model call would use, returns manual-entry fallback |
| Per-medicine AI explanation (Section 9.13) | Stubbed template — wire a real LLM call in `dashboardRoutes.js`, keeping `originalInstruction` and `plainLanguage` as separate fields |
| Minor Symptom Guidance (Section 9.14) | NOT implemented — architecture-only doc in `future-work/`, per the design doc's own scope constraint |

## Demo script for faculty

`npm run seed` runs the exact walkthrough from **Section 14** of the design
doc: upload → dose change → patient reports stopped → caregiver finds it
still available → conflict auto-detected → reason recorded (pharmacy
shortage) → caregiver notified → resolved → doctor export generated. Console
output narrates each step and prints the final structured doctor export as
JSON, which is the artifact meant to demonstrate "reconciliation with
follow-through," not just OCR-and-display.

## Testing

```bash
npm test
```

Covers the state engine, conflict detection (including the "no conflict once
discontinuation is confirmed" case), and the case lifecycle's resolve-once
guarantee.

## Notes for extending this

- **Never write to `events` except through `eventStore.appendEvent`.** That's
  what keeps the audit trail (9.7/9.8) a property of the data model instead
  of something you have to remember to keep in sync.
- **Never let the state engine or conflict detector mutate anything.** They
  should stay pure reads over the event log; only `caseLifecycle.js` and
  `eventStore.js` write.
- **Never let `safetyRulesService` imply an untested medicine is safe.**
  Uncovered pairs must return `NOT_COVERED`, not be silently skipped.
