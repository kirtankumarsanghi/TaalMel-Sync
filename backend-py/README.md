# Taalmel Sync backend (Phase 1)

Python 3.12 + FastAPI implementation of the Phase 1 reconciliation engine.

## What this covers

### Core loop (Phase 1)
**prescribed → observed → reconciled → why → action → resolved**

- Event store: append-only, typed payloads, idempotency keys.
- Auth: JWT access + rotating refresh tokens (argon2 hashing), consent-gated caregiver access, audit trail.
- Prescription intake: upload, SHA-256 dedupe per patient, OCR, human verification.
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

- **Documents** — `POST /api/documents/upload` accepts prescriptions, lab reports,
  discharge summaries, invoices, and unknown pages. It classifies the text, creates the
  structured row when possible, and always stores the raw document. Handwritten lines
  that the strict parser rejects are kept for human review, and a manual line can be
  added when OCR returns nothing.
- **OCR** reads PDF text layers first, then EasyOCR for printed scans. Handwritten Indian
  prescriptions need a cloud provider: `TAALMEL_OCR_ENGINE=gemini` with a Google AI Studio
  key (free tier), or `TAALMEL_OCR_ENGINE=google` with a Cloud Vision key. Local TrOCR is
  available through the `handwriting` extra but is not reliable on cursive. No OCR output
  becomes a medication without confirmation.
- **Notifications** are written as rows and delivered over a configured webhook or SMTP
  email. Without either configured, the row records `delivery_error="no delivery channel
  configured"` rather than pretending it was sent.
- **Background jobs** use the inline queue in development and ARQ + Redis when
  `TAALMEL_JOB_QUEUE=arq` or `TAALMEL_OCR_INLINE=false`.
- **Voice** accepts a browser-produced transcript (Web Speech API) or audio through
  Whisper if the optional `speech` extra is installed.
- **Photo verification** reads the packaging label with OCR and compares the text to the
  expected medicine. It is label verification, not image-similarity matching.
- **Pharmacy ordering** is a provider interface. With no API URL configured, the mock
  provider records the order locally for a pharmacist.
- **Curated dictionaries are illustrative**, not clinically validated.
- **Rate limiting is in-process memory**, so it resets on restart.
- **Doctor login is optional.** Public QR links still require no account; a doctor account
  exists only to save patients in a dashboard.

## Run it

```bash
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8010
# open http://127.0.0.1:8010/docs
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
  ocr/            OCR providers (PDF text, EasyOCR, Google Vision, Gemini, TrOCR)
  jobs/           queue adapters + ARQ worker
  data/           curated dictionaries (medication, safety, affordability)
alembic/          migrations
tests/            pytest suite
```
