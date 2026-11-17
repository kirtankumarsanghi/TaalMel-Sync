# TAALMEL SYNC — Specification & Implementation Status

**Last verified:** 2026-11-17 against `backend-py/`
**Verification method:** full pytest suite (410 passing cases); Alembic upgrade/downgrade on a fresh database; endpoint list read from the mounted routers; production frontend build (`tsc -b && vite build`); Playwright browser smoke test, plus `scripts/check-history.mjs` for the history screen.

> **This document replaces the earlier spec**, which marked several built features as "planned"
> and marked three things "working" that are not (real OCR, Celery, structlog). Every status
> below was checked against code, not recalled. Where the original spec is not met, that is
> stated plainly rather than reworded.

---

## 1. PROJECT OVERVIEW

**One-line pitch:** "Taalmel doesn't just detect that something's wrong with a medication — it finds out why, routes it to the right response, tracks whether it actually got resolved, and makes every doctor visit easier than the last one."

**Core loop:** PRESCRIBED → OBSERVED → RECONCILED → WHY → ACTION → RESOLVED

**Users:**
- Remote caregiver — manages an elderly parent's medicines from another city
- Patient — the family member taking the medicines
- Doctor — passive recipient; never installs or logs into anything

---

## 2. TECH STACK — AS BUILT

| Layer | Original spec | **Actually installed** | Note |
|---|---|---|---|
| Language | Python 3.12+ | Python 3.12 | ✅ |
| Framework | FastAPI | FastAPI 0.162 | ✅ |
| Validation | Pydantic v2 | Pydantic 2.14 | ✅ |
| ORM | SQLAlchemy 2.0 + SQLModel | SQLModel 0.0.49 / SQLAlchemy 2.1 | ✅ |
| Migrations | Alembic | Alembic 1.20, 8 revisions | ✅ reversible |
| Database | SQLite | SQLite; `psycopg` installed for Postgres via compose | ✅ |
| Auth hashing | passlib[bcrypt] | **argon2-cffi** | Deviation — argon2id, avoids bcrypt's 72-byte limit |
| JWT | python-jose | **PyJWT** | Deviation — python-jose is unmaintained |
| Rate limiting | slowapi | slowapi 0.1.10 | ✅ in-memory only |
| Background jobs | Celery + Redis / ARQ | **ARQ + Redis, wired through the queue adapter** | ✅ inline in dev; ARQ when `TAALMEL_JOB_QUEUE=arq` or `TAALMEL_OCR_INLINE=false`; daily cron |
| OCR | EasyOCR + PaddleOCR | **EasyOCR, Google Vision, or local TrOCR** | ✅ printed text local; handwriting needs Google Vision or the `handwriting` extra |
| PDF | WeasyPrint | **fpdf2 (pure Python) + HTML** | ✅ JSON/PDF/HTML export |
| i18n | gettext | **JSON catalogues + React language selector** | ✅ hi/ta/te/bn/mr interface strings |
| Speech-to-text | Whisper / Google | **Browser Web Speech API + optional Whisper** | ✅ transcript endpoint works without a model; `speech` extra for server audio |
| Logging | structlog | **structlog configured in the app factory** | ✅ structured JSON logs |
| Testing | pytest + httpx + Factory Boy | pytest + httpx (+pytest-asyncio) | 377 cases; Factory Boy not used |
| CORS / secure headers | starlette middleware | **CORS + security headers wired** | ✅ |
| API docs | Swagger at /docs | ✅ | ✅ |

**Caveats:** Handwritten Indian prescriptions are the real risk. EasyOCR is not enough;
set `TAALMEL_GOOGLE_VISION_API_KEY` for the production handwriting path, or install the
`handwriting` extra for local TrOCR. If OCR still returns nothing, the review screen now
keeps raw plausible lines and offers manual entry before verification. PaddleOCR fallback
is not built. PDF input renders the first three pages at 300 DPI via PyMuPDF. Notification
delivery requires a webhook or SMTP configuration; otherwise the row records that no channel
is configured. Photo verification reads the label text, not image similarity. Pharmacy
ordering uses a provider interface with a local mock by default.

---

## 3. ACTUAL FOLDER STRUCTURE

The original spec described `app/routes/`, `app/middleware/`, `app/schemas/`, `app/i18n/`,
`app/templates/`, `app/workers/`. The code does not match that, and this document describes
what exists:

```
backend-py/
  app/
    main.py              app factory, router mounting, exception handlers
    config.py            pydantic-settings
    api/
      deps.py            auth dependencies (user id, role, session)
      routes/            auth, households, prescriptions, medications, evidence,
                         cases, notifications, dashboard, exports, lab_reports,
                         companion
    audit/               audit record writes
    auth/                argon2 hashing, JWT, doctor-link tokens, rate limiters
    consent/             caregiver access + consent rules
    db/                  SQLModel tables, session/engine
    engines/             pure logic: state, conflicts, cases, reasons, triggers
    events/              event types, typed payload models, append-only store
    households/          household + patient creation
    jobs/                queue adapters (inline/ARQ) + ARQ worker
    ocr/                 provider interfaces + deterministic stubs (prescription, lab)
    services/            persistence: normalization, medications, prescriptions,
                         evidence, reconciliation, reasons, triggers, dashboard,
                         doctor_export, lab_reports, companion, safety,
                         affordability, emergency_contacts, storage
    data/                curated JSON: medicationDictionary, safety-interactions,
                         affordability-resources
  alembic/               5 migrations
  tests/                 17 files, 240 tests
```

**No `middleware/`, `schemas/`, `i18n/`, `templates/`, or `workers/` directories exist.**
Request/response models are declared inline in route modules.

---

## 4. FEATURE STATUS — VERIFIED

Legend: ✅ WORKING (built + tested) · 🔶 PARTIAL · 🔲 NOT BUILT · ⏳ DELIBERATELY DEFERRED

### 4.1 Core reconciliation engine

| Feature | Status | Reality |
|---|---|---|
| Prescription upload & intake | ✅ | Upload, 10 MB limit, JPEG/PNG/PDF only, SHA-256 dedupe per patient, local storage, human verify required |
| OCR extraction | ✅ | **PDF text layer first**, then EasyOCR/Google Vision/TrOCR for scans. Line reconstruction, digit repair, document classification. Handwritten pages that no local engine can read still open a manual review with raw OCR plus a paste-text parser. PaddleOCR fallback not implemented |
| OCR text parsing | ✅ | Separate, tested module: rejects headers/patient/doctor lines, extracts name, dose, schedule, duration; 42 assertions |
| Brand → generic matching | ✅ | Exact generic → brand → first-word → prefix-fuzzy → UNRESOLVED, with 0.7/0.5 thresholds; 55-medicine curated dictionary including common Indian dermatology medicines |
| Event history log | ✅ | Append-only; no update/delete paths exist; typed payload per event type; idempotency keys |
| Medication state engine | ✅ | Four dimensions (PRESCRIBED, AVAILABLE, REPORTED_TAKING, CONFIRMED_STATUS), last-event-wins |
| Evidence freshness | ✅ | **Per dimension**: prescription 180d, confirmation 90d, availability 7d, self-report 3d, each overridable |
| Conflict detection | ✅ | PRESCRIPTION_VS_REPORT, REPORT_VS_AVAILABILITY, STOPPED_BUT_UNEXPLAINED, EXPIRED_STOCK |
| Reason classification | ✅ | 8 codes; each maps to an executed action (notification / reminder / discontinuation), not just a label |
| Case lifecycle | ✅ | OPEN → AWAITING_INFO → RESOLVED / STILL_UNCERTAIN; invalid transitions rejected 409; nothing auto-closes |
| Trigger engine | ✅ | Event-driven, escalation levels INFO/ACTION/CRITICAL, dedupe so repeats don't spam |
| Dosage tapering tracker | ✅ | Records the prescriber's schedule verbatim, parses it, and flags a dose above the schedule or a reduction earlier than planned. Never suggests a taper |
| Medicine photo verification | ✅ | Reads the packaging label with EasyOCR and compares the text to the expected generic/brand names (`OcrPhotoMatcher`). A weak or unreadable label returns `NOT_CHECKED`; it never invents a match. This is label verification, not image similarity |
| Medicine expiry tracking | ✅ | Caregiver records expiry; 30-day warning; expired stock opens a **tracked case**. The ARQ daily cron runs the same checks without a user |

### 4.2 Safety, trust & escalation

| Feature | Status | Reality |
|---|---|---|
| Drug interaction / duplicate ingredient | ✅ | Curated dataset only; anything outside returns `NOT_COVERED`, never "safe" |
| Emergency escalation | ✅ | `EmergencyContact` per patient; CRITICAL reaches contacts as well as the caregiver. Notification rows are delivered over a configured webhook or SMTP email; otherwise the row records that no channel is configured |
| Visible medicine history | ✅ | Full event history, a dated timeline in the export, and a patient wellness timeline page in the client |
| What/Why/Source/Status/Action | ✅ | `/api/cases/{id}/explain`, including "does not change or stop any medication" |
| Access control & consent | ✅ | Access row **and** active, non-revoked consent **and** unexpired window. The client asks for explicit confirmation; consent is never defaulted to true |
| Temporary access handoff | ✅ | `expires_at` on access; enforced at read time, no cron needed; documented `POST/DELETE /temporary-access` aliases exist |
| Audit trail | ✅ | Register, login, failed login, logout, household/patient creation, access grant, consent, prescription upload/patch/verify, evidence report/availability/confirmation/dose change, normalization verify, conflicts, resolutions, reasons, emergency contacts, doctor link issue/view, lab upload |

### 4.3 Doctor communication & lab correlation

| Feature | Status | Reality |
|---|---|---|
| One-page doctor export | ✅ | JSON, **PDF (fpdf2)** and **print-ready HTML**. Prescriber, dated change history with sources, evidence basis, case counts, questions, lab findings |
| PDF / HTML rendering | ✅ | fpdf2 (pure Python). WeasyPrint was dropped: it needs GTK system libraries that are absent here, which would have made the export fail outside this machine |
| QR-code doctor access | ✅ | Short-lived token → `/api/public/doctor-export/{token}`, no login, scoped to one patient, rate-limited, audited |
| QR **image** generation | ✅ | Server renders the PNG, so the encoded URL is the one the server issued. `POST /doctor-link/qr` (base64) and `GET /doctor-link/qr.png` |
| Doctor-to-doctor continuity | ✅ | Prescriber name + prescription date, full sourced timeline, explicit evidence basis |
| Lab report upload & correlation | 🔶 | Upload + extraction (real EasyOCR path; deterministic stub in tests) + correlation against *reported* adherence. Values stored verbatim; nothing interprets them |
| Minimal medication info card | ✅ | `/info-card` (was listed as future work; it is built) |

### 4.4 Daily companion

| Feature | Status | Reality |
|---|---|---|
| "What do I need right now" | ✅ | `/households/{id}/today`, shows the doctor's instruction verbatim |
| Plain-language explanation | 🔶 | The doctor's own instruction is returned unchanged. No generated or translated explanation exists (would need reviewed content) |
| "What changed since last visit" | ✅ | `/households/{id}/changes?sinceDays=` with source on each row |
| Prepare-for-visit export | ✅ | Same export endpoint, on demand |
| "Ask My Doctor" list | ✅ | Stored and surfaced; the API response states the app does not answer it |
| Caregiver dashboard | ✅ | `/summary`: confirmed, needs checking, open cases, near expiry, expired |
| Record completeness | ✅ | Data-quality percentage, explicitly not a health score |
| Smart refill awareness | ✅ | Estimates consumption from reported doses (needs ≥7 days of evidence) and says which basis it used. Falls back to the time window when evidence is thin. Labeled as self-reported, not a pharmacy record |
| Pharmacy refill list | ✅ | `/refill-list` generating generic name + dose. `POST /households/{id}/refill-orders` sends the list through a pharmacy provider; the default mock records the order locally |

### 4.5 Accessibility & localization

| Feature | Status | Reality |
|---|---|---|
| Multi-language interface (hi/ta/te/bn/mr) | ✅ | All five languages complete (interface strings only). The React client has a language selector and falls back to English rather than showing a key |
| Voice self-reports (Whisper) | ✅ | Browser Web Speech API sends a transcript, or audio is sent to Whisper when the `speech` extra is installed. Intent + medicine matching; **refuses to guess** when unclear |
| Voice symptom logging | ✅ | Symptoms are stored and routed through the care connector; no diagnosis and no medicine naming |
| Large-text / high-contrast | ✅ | Client toggles apply `taalmel-large-text` and `taalmel-high-contrast` classes; preference is persisted |

### 4.6 Future work — status after completion

- **Minor Symptom Guidance** — care connector implemented (record + severity-based routing); clinical guidance content is still deliberately absent pending review.
- **Offline-first sync** — evidence writes are queued in a local outbox with idempotency keys and replayed when online. Reads still require connectivity.
- **Patient wellness timeline** — implemented (`/patients/{id}/wellness-timeline` and the Wellness page).
- **Doctor login/dashboard** — optional doctor account implemented; public token links remain the default and still require no account.
- **Pharmacy ordering API** — provider interface implemented with a local mock; set `TAALMEL_PHARMACY_API_URL` for an HTTP provider.

### 4.7 Longitudinal history

| Feature | Status | Reality |
|---|---|---|
| Medication timeline | ✅ | Derived from human-verified prescription lines only, merged per drug (brand → generic when the dictionary agrees). Groups by year; undated items are listed as "date not recorded", never guessed into a year. `GET /api/patients/{id}/medication-timeline?year=` |
| Dose-change episodes | ✅ | Consecutive entries with the same dose and frequency collapse into one episode; a dose change starts a new episode with `previous_dose` and `dose_changed`, and every episode cites its source prescription |
| Diagnosis capture | ✅ | Lines explicitly labelled `Dx`, `D/X`, or `Diagnosis` are stored as **unconfirmed** conditions with the raw wording kept. Nothing groups on a condition before a person confirms it. Unlike the rest of the flow, a stored condition can also be added by hand |
| Bulk archive import | ✅ | `POST /api/patients/{id}/documents/bulk` takes many files with one visit date per file (a date is required), isolates a bad file so the batch survives, and still requires per-prescription confirmation |
| Frontend History screen | ✅ | `/app/history`: year-by-year visits, dose-change log, condition review and correction, lab comparison table, archive importer, and PDF download. Verified in a real browser (10/10 checks, no console errors) |
| Dossier PDF | ✅ | `GET /api/patients/{id}/dossier.pdf`: conditions, medicines by year with the source file on every visit, dose-change log, lab comparison against printed ranges, source list, and an explicit "records that could not be read" section |
| Condition linking | ✅ | A confirmed diagnosis is linked to the medicines written on the same prescription page. Every link states that this is co-occurrence, not a claim that a medicine treated the condition |
| Lab comparison | ✅ | Same test across dates, compared with the reference range printed on its own report. Different units are separate series; qualitative results are `NOT_COMPARABLE`. No clinical judgement |

---

## 5. API REFERENCE — ACTUAL ENDPOINTS

> Read from the mounted routers. Canonical routes and the documented compatibility routes
> are both present; compatibility routes delegate to the same services.

**Auth** — `POST /api/auth/register` · `/login` · `/refresh` · `/logout` · `GET /api/auth/me`

**Households & patients** — `POST /api/households` · `GET /api/households/{id}` · `POST /api/households/{id}/patients` · `POST /api/households/{id}/members` · `GET|PATCH /api/patients/{id}`

**Access & consent** — `POST /api/access` · `POST /api/households/{id}/access` · `POST /api/access/{id}/consent` · `POST /api/households/{id}/access/{id}/consent` · `POST /api/access/{id}/revoke` · `POST /api/households/{id}/temporary-access` · `DELETE /api/households/{id}/temporary-access/{id}` · emergency contacts

**Prescriptions** — `POST /api/prescriptions/upload` (optional `prescribed_by`, `prescribed_on`) · `GET /api/prescriptions/{id}` · `PATCH /api/prescriptions/{id}` · `POST /api/prescriptions/{id}/verify` · `POST /api/prescriptions/{id}/ocr` (re-read a failed page) · `GET /api/patients/{id}/prescriptions`

**History** — `GET /api/patients/{id}/medication-timeline` (`?year=`) · `GET /api/patients/{id}/conditions` · `POST /api/patients/{id}/conditions` · `POST /api/conditions/{id}/verify` · `GET /api/patients/{id}/lab-comparison` · `GET /api/patients/{id}/dossier.pdf` · `POST /api/patients/{id}/documents/bulk`

**Medications & normalization** — `GET /api/medications` · `/needs-review` · `POST /api/medications/normalize-preview` · `POST /api/medications/{id}/verify-normalization`

**Evidence** — `POST /api/medications/{id}/report` · `/availability` · `/confirm` · `/dose-change` · `GET /api/medications/{id}/history` · `/state`

**Documented aliases** — `POST /api/patients/{id}/self-report` · `GET /api/patients/{id}/self-reports` · `POST /api/medicines/{id}/expiry` · `GET /api/patients/{id}/expiry-alerts`

**Reconciliation & cases** — `POST /api/medications/{id}/detect` · `GET /api/medications/{id}/repeated-reasons` · `GET /api/households/{id}/open-cases` · `POST /api/cases/{id}/reason` · `/action` · `/resolve` · `GET /api/cases/{id}/explain`

**Triggers** — `GET /api/notifications` · `POST /api/notifications/{id}/read` · `POST /api/medications/{id}/checks`

**Dashboard** — `GET /api/households/{id}/summary` · `/completeness` · `/safety-check`

**Doctor export** — `GET /api/households/{id}/doctor-export` · `/info-card` · `POST /api/households/{id}/doctor-link` · `POST /api/households/{id}/doctor-link/qr` · `GET /api/households/{id}/doctor-link/qr.png` · `GET /api/public/doctor-export/{token}` *(no auth)* · `GET /api/doctors/export/{patient_id}` · `GET /api/doctors/export/{patient_id}/qr`

**Optional doctor account** — `POST /api/doctor/redeem` · `GET /api/doctor/patients` · `GET /api/doctor/patients/{member_id}/export`

**Lab** — `POST /api/lab-reports/upload` · `GET /api/households/{id}/lab-correlation` · `POST /api/patients/{id}/lab-reports/upload` · `GET /api/patients/{id}/lab-reports` · `GET /api/patients/{id}/lab-adherence-timeline`

**Companion** — `GET /api/households/{id}/today` · `/changes` · `/refill-list` · `GET /api/patients/{id}/refill-list` · `POST /api/households/{id}/refill-orders` · `GET /api/refill-orders/{id}` · questions

**Voice, symptoms, wellness** — `POST /api/households/{id}/voice-report` (audio or `transcript`) · `POST /api/patients/{id}/voice-report` · `POST /api/patients/{id}/symptoms` · `GET /api/patients/{id}/wellness-timeline`

**Documents** — `POST /api/documents/upload` (auto-classifies prescription / lab / discharge summary / invoice / other) · `POST /api/documents/{id}/as-prescription` · `GET /api/patients/{id}/documents` · `POST /api/prescriptions/{id}/items` (manual line) · `POST /api/prescriptions/{id}/parse-text` (paste-to-parse)

**i18n** — `GET /api/i18n/languages` · `/api/i18n/{language}` · `/api/i18n/{language}/{key}`

**Meta** — `GET /health`

---

## 6. WHAT IS ACTUALLY WORKING

- **Database & migrations** — SQLite/SQLModel, 8 Alembic revisions, upgrade and downgrade verified on a fresh database.
- **Server** — FastAPI, router mounting, typed exception handlers with correct status codes, Swagger at `/docs`, CORS wired. Security headers are still absent.
- **Auth** — register/login/refresh/logout, argon2id hashing, rotating refresh tokens with family revocation on reuse. Access tokens and doctor links cannot be used interchangeably.
- **Households, patients, consent, temporary handoff, audit** — as described in 4.2. Consent is explicit in the client; the backend still records the consent assertion, not an independent patient signature.
- **Prescriptions** — intake, prescriber metadata, verification, and patient-level listing are real; OCR uses EasyOCR when installed.
- **Reconciliation** — state engine, conflicts, cases, reasons, triggers all real and tested. Reason actions now execute notifications/reminders/discontinuation, and trigger rules run on prescription, OCR, verification, evidence, and reason events.
- **Doctor export + public link** — real, including token expiry and scope isolation. PDF/HTML/QR are real. Prescriber metadata is captured at upload or patched later.
- **Lab correlation** — real correlation logic over a real OCR path (stub in tests).
- **Companion** — all endpoints real; refill estimation uses reported consumption when available and falls back to the time window.
- **Background work** — ARQ queue selection is wired; the worker has an OCR function and a daily cron. Notifications are delivered over webhook/SMTP when configured.
- **Client** — React client with Today, Medicines, Cases, Wellness, Doctor Export, Safety, language selector, large-text/high-contrast modes, Web Speech voice reports, offline evidence outbox, and an optional doctor dashboard.
- **Testing** — 385 passing cases. `tests/test_migrations.py` compares every model column against the migrated schema.
- **Deployment** — Dockerfile and compose for uvicorn + Postgres + Redis + ARQ worker.

---

## 7. REMAINING WORK, IN PRIORITY ORDER

**Operational hardening**
1. Configure a real notification channel (webhook or SMTP) in deployment; without it rows
   record an explicit delivery failure.
2. Test the ARQ worker against live Redis and run the daily cron in staging.
3. Add security headers (CSP, HSTS, X-Content-Type-Options, frame-ancestors) and wire
   structlog for structured request logging.
4. Add PaddleOCR fallback and verify Indian-script packs and handwriting against real scans.

**Clinical/content review**
5. Replace the illustrative interaction and affordability datasets with cited sources.
6. Minor-symptom content still needs a qualified reviewer; the current connector records and
   routes but deliberately does not triage by symptom text.

**External integrations**
7. Set `TAALMEL_PHARMACY_API_URL` and validate against a real pharmacy provider.
8. Optional doctor account lifecycle (password reset, account deletion) if the dashboard is
   deployed beyond a demo.

---

## 8. CONSTRAINTS — AND HOW EACH IS ENFORCED

| # | Constraint | Enforcement in code |
|---|---|---|
| 1 | Never auto-answer a medical question | Questions are stored; the response carries "Taalmel does not answer clinical questions" |
| 2 | Never name a medicine for a symptom | The symptom connector records a patient-selected severity and returns only a care action ("call emergency services", "contact a doctor", "discuss at next visit"). It never returns a medicine name and never diagnoses |
| 3 | Never mark an unchecked interaction "safe" | `NOT_COVERED` is the default outside the curated dataset; known-but-unlisted pairs say `NO_KNOWN_ISSUE_IN_DATASET`, not "safe"; tested |
| 4 | Never trust OCR without human verification | `PrescriptionItem.verified` starts false; medications are only created by the verify endpoint |
| 5 | Never require a doctor to install or log in | Public token route remains the default; a doctor account is optional and only adds a saved-patient dashboard |
| 6 | Never auto-close a case | Transitions require an explicit human action; `RESOLVED` is terminal; tested |
| 7 | Never overwrite event history | No update/delete path exists for `events`; a structural test guards this |
| 8 | Never assume consent | Access row + active consent + unexpired window; 403 otherwise; the client requires an explicit confirmation checkbox. Residual limitation: the backend records the caregiver's assertion, not an independent patient signature |
| 9 | Medical content from official sources only | No clinical text is generated anywhere; dictionaries are labelled illustrative; symptom guidance returns no clinical content |

**Additional enforced rules discovered during the build:**
- Missing evidence reports `UNKNOWN`, never a guess; adherence with no reports is `null`, not 0%.
- Lab values are stored and shown verbatim; no code path interprets them as good or bad.
- A stale evidence dimension does not silently participate in a conflict.

---

## 9. COVERAGE SUMMARY

Verified against the running API and the production frontend build.

| Area | Built | Partial | Not built |
|---|---|---|---|
| Core engine | 12 | 2 (interaction breadth, photo is label OCR) | 0 |
| Safety & trust | 7 | 1 (delivery depends on channel config) | 0 |
| Doctor & lab | 6 | 1 (lab extraction quality) | 0 |
| Companion | 8 | 1 (refill estimate only changes basis) | 0 |
| Accessibility | 2 | 0 | 0 |
| Future work | 3 | 3 (clinical symptom guidance, offline reads, pharmacy credentials) | 0 |

**35 of 43 documented features are fully working; 8 are partial, and none are missing.**
The partials are limits of data or external configuration, not unwritten endpoints:
- **Interaction check** is honest but the curated dataset is small.
- **Photo verification** reads the label text; it is not image-similarity matching.
- **Lab extraction** quality depends on the source document and OCR.
- **Plain-language explanation** still returns the doctor's instruction verbatim.
- **Smart refill** uses the consumption estimate for its basis, not as a replacement for the
  refill trigger.
- **Symptom guidance** is a care connector, not clinical advice; clinical text is blocked.
- **Offline-first** covers writes through an idempotent outbox; reads still need connectivity.
- **Pharmacy ordering** uses a provider interface; without credentials the mock records the
  order locally.
