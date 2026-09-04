# Minor Symptom Guidance & Care Connector — Architecture Only

**Status: NOT implemented. Documented per Section 9.14's honest scope
constraint.** The `symptom_checks` table exists in the schema
(`src/db/schema.sql`) so the event-logging shape can be demonstrated, but
no clinical content — self-limiting symptom list, red-flag thresholds,
self-care guidance text — is included anywhere in this codebase.

## Why this is scoped out, not just deferred

Fever in the target population can indicate something far more serious
than a cold (dengue, malaria, etc.). A tool that quietly encourages
skipping a doctor visit would be actively dangerous. Building the actual
clinical-content layer requires review from a qualified healthcare
professional, or a genuine content partnership with a public health
source (ICMR/MoHFW/WHO patient-facing materials) — not engineering
judgment alone.

## If this is picked up later, the intended architecture is:

```
Patient enters a symptom
        ↓
Deterministic rule-match against a small, fixed set of
genuinely self-limiting complaints (sourced only from named
official guidance, never AI-generated)
        ↓
Any red flag present? (duration, severity, comorbidity,
accompanying symptoms — fixed, reviewed thresholds)
   ┌────┴────┐
  YES        NO — within the narrow self-limiting band
   ↓                        ↓
"See a doctor      General, already-published self-care
promptly" —         guidance, always shown with its source
shown clearly,             ↓
no exceptions      Offer lower-cost next steps (telemedicine,
                    pharmacist, "monitor and re-check in 24h")
                            ↓
                    Logged as an event (symptom_checks table)
```

Key implementation rules if this is ever built for real:

1. Every guidance string must trace to a named, static, official source
   shown to the patient — no generated text.
2. Red-flag thresholds are fixed at build time by a reviewer with medical
   qualifications, not tunable by conversation phrasing.
3. Never return "you're fine, no need to see anyone" — always end with a
   concrete next step.
4. `symptom_checks.red_flag_matched` and `.outcome` should never be
   written by this feature until content has been reviewed; leave them
   NULL / 'NOT_EVALUATED' in any interim demo.
