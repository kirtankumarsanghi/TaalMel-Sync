# Taalmel Sync backend (Phase 1)

Python 3.12 + FastAPI implementation of the Phase 1 reconciliation engine.

## What this covers

### Core loop (Phase 1)
**prescribed → observed → reconciled → why → action → resolved**

- Event store: append-only, typed payloads, idempotency keys.
- Auth: JWT access + rotating refresh tokens (argon2 hashing), consent-gated caregiver access, audit trail.
- Prescription intake: upload, SHA-256 dedupe per patient, OCR job (stub provider), verification.
- Normalization: brand/generic/strength/form/frequency matching over a curated dictionary.
- Evidence: self-report, physical availability (with expiry), status confirmation, dose changes.
- State engine: four evidence dimensions, each with its own freshness window.
- Conflict detection: including expired stock, which opens a tracked case.
- Case lifecycle, eight reason codes with executed actions, repeated-reason detection.
- Triggers: notifications with escalation levels, refill window, expiry warnings, emergency contacts.

### Doctor communication and follow-through
- Doctor export with prescriber, dated change history and sources, and an explicit evidence basis.
- Time-limited public link (QR-ready) so a doctor can read it without an account.
- Minimal info card.
- Lab report upload, with values stored as printed and correlated against *reported* adherence.

### Daily companion
- Today's medicines, "what changed", Ask My Doctor list, refill list.
- Temporary access handoff that expires on its own.

## Design rules enforced in code

- **Append-only events.** There are no update or delete paths for `events`. Corrections are new events.
- **One payload model per event type**, shared by routes and engines.
- **Consent is explicit.** Access needs a row *and* active, non-revoked consent, *and* an unexpired window.
- **Two token types never mix.** Access tokens carry `typ: access`; doctor links carry `typ: doctor_export`. Each is rejected where the other belongs.
- **Missing evidence is UNKNOWN, never guessed.** Dimensions with no evidence do not report a value, and adherence with no reports is `null`, not 0%.
- **Freshness is per dimension.** A prescription lasts months; a cabinet check lasts days. These are engineering defaults, not clinical thresholds.
- **Safety is honest.** A medicine outside the interaction dataset returns `NOT_COVERED`, never "safe".
- **No medical advice.** The app records reasons and routes to professionals; it never names a medicine, interprets symptoms, or interprets a lab value.
- **Nothing is silently dropped.** A case stays open until someone resolves it.

## Known limitations

- **OCR is a stub** (prescription and lab). Real EasyOCR/PaddleOCR is a later phase.
- **No client.** Patient screens, multilingual layout, large-text and high-contrast modes, and the QR image itself are UI work. This repo is the backend only.
- **i18n and voice input are not built.** The API takes text and serves strings in English.
- **Notifications are stored, never sent.** No SMS/push/email delivery exists.
- **Tapering and photo verification are not built.**
- **The ARQ worker path is untested** against live Redis; only the inline path is covered.
- **Curated dictionaries are illustrative**, not clinically validated.
- **Rate limiting is in-process memory**, so it resets on restart.

## Run it

```bash
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
# open http://127.0.0.1:8000/docs
```

Tests:

```bash
uv run pytest
```

The end-to-end scenario lives in `tests/test_scenario_phase1.py`.

## Layout

```
app/
  api/routes/     HTTP endpoints
  auth/           passwords, tokens, doctor links
  consent/        access + consent rules
  audit/          audit records
  db/             SQLModel tables, session
  events/         event types, payload models, store
  engines/        state, conflicts, cases, reasons, triggers (pure logic)
  services/       persistence around the engines
  ocr/            OCR provider interfaces + stubs (prescription and lab)
  jobs/           queue adapters + ARQ worker
  data/           curated dictionaries (medication, safety, affordability)
alembic/          migrations
tests/            pytest suite
```
