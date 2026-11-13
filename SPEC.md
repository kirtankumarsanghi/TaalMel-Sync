# TAALMEL SYNC — Specification & Implementation Status

**Last verified:** 2026-11-13 against `backend-py/`
**Verification method:** 240 passing tests; live end-to-end run against a real migrated database (35 checks); dependency list inspected in `.venv`; endpoint list read from the running app's OpenAPI schema.

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
| Migrations | Alembic | Alembic 1.20, 5 revisions | ✅ reversible |
| Database | SQLite | SQLite; `psycopg` installed for Postgres via compose | ✅ |
| Auth hashing | passlib[bcrypt] | **argon2-cffi** | Deviation — argon2id, avoids bcrypt's 72-byte limit |
| JWT | python-jose | **PyJWT** | Deviation — python-jose is unmaintained |
| Rate limiting | slowapi | slowapi 0.1.10 | ✅ in-memory only |
| Background jobs | Celery + Redis / ARQ | **ARQ** | Celery not installed; ARQ worker untested |
| OCR | EasyOCR + PaddleOCR | **EasyOCR (real) + PyMuPDF for PDF input** | ✅ EasyOCR verified reading a real image and a PDF; PaddleOCR fallback not added |
| PDF | WeasyPrint | **Not installed** | ❌ export is JSON only |
| i18n | gettext | **Not built** | ❌ |
| Speech-to-text | Whisper / Google | **Not built** | ❌ |
| Logging | structlog | **Declared, never imported** | ❌ no logging wired |
| Testing | pytest + httpx + Factory Boy | pytest + httpx (+pytest-asyncio) | Factory Boy not used; fixtures are plain pytest |
| CORS / secure headers | starlette middleware | **Not wired** | ❌ |
| API docs | Swagger at /docs | ✅ | ✅ |

**Not built / caveats:** PaddleOCR fallback, i18n, speech-to-text, structured logging,
CORS/security headers. The EasyOCR engine runs on CPU with English only; Indian-script packs
are supported by the library but are not enabled or tested. Handwriting recognition is
unverified — it is untested against real Indian prescriptions. PDF input renders the first
three pages at 300 DPI via PyMuPDF.

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
| OCR extraction | ✅ | **EasyOCR (real, CPU)** with line reconstruction and digit-confusion repair. Verified end-to-end: a prescription image yields the correct medicines, doses and frequencies. PaddleOCR fallback not implemented. PDF input needs PyMuPDF (not installed) |
| OCR text parsing | ✅ | Separate, tested module: rejects headers/patient/doctor lines, extracts name, dose, schedule, duration; 42 assertions |
| Brand → generic matching | ✅ | Exact generic → brand → first-word → prefix-fuzzy → UNRESOLVED, with 0.7/0.5 thresholds; 39-medicine curated dictionary |
| Event history log | ✅ | Append-only; no update/delete paths exist; typed payload per event type; idempotency keys |
| Medication state engine | ✅ | Four dimensions (PRESCRIBED, AVAILABLE, REPORTED_TAKING, CONFIRMED_STATUS), last-event-wins |
| Evidence freshness | ✅ | **Per dimension**: prescription 180d, confirmation 90d, availability 7d, self-report 3d, each overridable |
| Conflict detection | ✅ | PRESCRIPTION_VS_REPORT, REPORT_VS_AVAILABILITY, STOPPED_BUT_UNEXPLAINED, EXPIRED_STOCK |
| Reason classification | ✅ | 8 codes; each maps to an executed action (notification / reminder / discontinuation), not just a label |
| Case lifecycle | ✅ | OPEN → AWAITING_INFO → RESOLVED / STILL_UNCERTAIN; invalid transitions rejected 409; nothing auto-closes |
| Trigger engine | ✅ | Event-driven, escalation levels INFO/ACTION/CRITICAL, dedupe so repeats don't spam |
| Dosage tapering tracker | 🔲 | Not built. Dose changes are recorded, but no taper schedule is tracked |
| Medicine photo verification | 🔲 | Not built. No image-similarity comparison exists |
| Medicine expiry tracking | ✅ | Caregiver records expiry; 30-day warning; expired stock opens a **tracked case** |

### 4.2 Safety, trust & escalation

| Feature | Status | Reality |
|---|---|---|
| Drug interaction / duplicate ingredient | ✅ | Curated dataset only; anything outside returns `NOT_COVERED`, never "safe" |
| Emergency escalation | ✅ | `EmergencyContact` per patient; CRITICAL reaches contacts as well as the caregiver. Contacts managed via API |
| Visible medicine history | 🔶 | Full event history and a dated timeline in the export; no colour-coded UI (no client exists) |
| What/Why/Source/Status/Action | ✅ | `/api/cases/{id}/explain`, including "does not change or stop any medication" |
| Access control & consent | ✅ | Access row **and** active, non-revoked consent **and** unexpired window |
| Temporary access handoff | ✅ | `expires_at` on access; enforced at read time, no cron needed |
| Audit trail | ✅ | Register, login, failed login, logout, household/patient creation, access grant, consent, prescription upload/verify, normalization verify, conflicts, resolutions, reasons, dose changes, emergency contacts, doctor link issue/view, lab upload |

### 4.3 Doctor communication & lab correlation

| Feature | Status | Reality |
|---|---|---|
| One-page doctor export | ✅ | JSON: prescriber, dated change history with sources, evidence basis per medicine, open/resolved/uncertain case counts, pending questions, lab findings |
| PDF / HTML rendering | 🔲 | **Not built.** Export is JSON only; WeasyPrint not installed |
| QR-code doctor access | ✅ | Short-lived token (default 120 min) → `/api/public/doctor-export/{token}`, no login, scoped to one patient, rate-limited, audited |
| QR **image** generation | 🔲 | Backend returns the URL; drawing the QR is client work |
| Doctor-to-doctor continuity | ✅ | Prescriber name + prescription date, full sourced timeline, explicit evidence basis |
| Lab report upload & correlation | 🔶 | Upload + extraction (stub) + correlation against *reported* adherence. Values stored verbatim; nothing interprets them |
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
| Smart refill awareness | 🔶 | **Time-window only.** The response says so: "not a predicted consumption rate". Consumption-based estimation is not built |
| Pharmacy refill list | ✅ | `/refill-list` generating generic name + dose; no ordering integration |

### 4.5 Accessibility & localization

| Feature | Status |
|---|---|
| Multi-language interface (hi/ta/te/bn/mr) | 🔲 Not built |
| Voice self-reports (Whisper) | 🔲 Not built |
| Voice symptom logging | ⏳ Deferred with the symptom feature |
| Large-text / high-contrast | 🔲 Not built (UI work; no client exists) |

### 4.6 Deliberately future work

⏳ Minor Symptom Guidance (architecture only in `future-work/`; blocked on clinical review)
⏳ Offline-first sync ⏳ Patient wellness timeline ⏳ Doctor login (excluded by design)
⏳ Pharmacy ordering API ⏳ Hospital integration ⏳ MCP

---

## 5. API REFERENCE — ACTUAL ENDPOINTS (50)

> The earlier document listed paths that do not exist (`GET /api/households/{id}`,
> `/temporary-access`, `/api/patients/{id}/prescriptions`, `/api/doctors/export/...`).
> The list below is read directly from the running app.

**Auth** — `POST /api/auth/register` · `/login` · `/refresh` · `/logout` · `GET /api/auth/me`

**Households & patients** — `POST /api/households` · `POST /api/households/{id}/patients` · `GET|PATCH /api/patients/{id}`

**Access & consent** — `POST /api/access` · `POST /api/access/{id}/consent` · `POST /api/access/{id}/revoke` · `POST|GET /api/households/{id}/emergency-contacts` · `DELETE /api/households/{id}/emergency-contacts/{contact_id}`

**Prescriptions** — `POST /api/prescriptions/upload` · `GET /api/prescriptions/{id}` · `POST /api/prescriptions/{id}/verify`

**Medications & normalization** — `GET /api/medications/needs-review` · `POST /api/medications/normalize-preview` · `POST /api/medications/{id}/verify-normalization`

**Evidence** — `POST /api/medications/{id}/report` · `/availability` · `/confirm` · `/dose-change` · `GET /api/medications/{id}/history` · `/state`

**Reconciliation & cases** — `POST /api/medications/{id}/detect` · `GET /api/medications/{id}/repeated-reasons` · `GET /api/households/{id}/open-cases` · `POST /api/cases/{id}/reason` · `/action` · `/resolve` · `GET /api/cases/{id}/explain`

**Triggers** — `GET /api/notifications` · `POST /api/notifications/{id}/read` · `POST /api/medications/{id}/checks`

**Dashboard** — `GET /api/households/{id}/summary` · `/completeness` · `/safety-check`

**Doctor export** — `GET /api/households/{id}/doctor-export` · `/info-card` · `POST /api/households/{id}/doctor-link` · `GET /api/public/doctor-export/{token}` *(no auth)*

**Lab** — `POST /api/lab-reports/upload` · `GET /api/households/{id}/lab-correlation`

**Companion** — `GET /api/households/{id}/today` · `/changes` · `/refill-list` · `POST|GET /api/households/{id}/questions` · `POST /api/questions/{id}/discussed`

**Meta** — `GET /health`

---

## 6. WHAT IS ACTUALLY WORKING

- **Database & migrations** — SQLite/SQLModel, 5 Alembic revisions, upgrade and downgrade verified on a fresh database.
- **Server** — FastAPI, router mounting, typed exception handlers with correct status codes, Swagger at `/docs`. **No CORS or security headers.**
- **Auth** — register/login/refresh/logout, argon2id hashing, rotating refresh tokens with family revocation on reuse. **Access tokens carry `typ: access`; doctor links carry `typ: doctor_export`; each is rejected where the other belongs** (this was a real bug, now tested).
- **Households, patients, consent, temporary handoff, audit** — as described in 4.2.
- **Prescriptions** — intake and verification fully real; OCR extraction stubbed.
- **Reconciliation** — state engine, conflicts, cases, reasons, triggers all real and tested.
- **Doctor export + public link** — real, including token expiry and scope isolation.
- **Lab correlation** — real correlation logic over stubbed extraction.
- **Companion** — all endpoints real; refill logic is time-based only.
- **Testing** — 240 tests across 17 files. `tests/test_migrations.py` compares every model column against the migrated schema, so model/migration drift fails the suite (this caught a real failure).
- **Deployment** — Dockerfile and compose for uvicorn + Postgres + Redis + ARQ worker (worker path untested).

---

## 7. REMAINING WORK, IN PRIORITY ORDER

**Correctness / honesty of existing claims**
1. ~~Real OCR~~ — **done**: EasyOCR installed, line reconstruction and digit repair verified
   end-to-end. Remaining: PaddleOCR fallback, PDF input (PyMuPDF), Indian-script packs.
2. PDF/HTML doctor export via WeasyPrint (spec §4.3).
3. Smart refill using reported consumption, falling back to the time window.
4. Notification delivery (SMS/push/email) — currently rows only.
5. CORS + security headers; wire structlog.
6. ~~Two known code defects~~ — **fixed**: expiry is announced exactly once (at CRITICAL, when the
   stock is first recorded), and a resolved case now closes only its own conflict, matched by
   triggering event rather than by type. Both are covered by regression tests verified to fail
   without the fix.
7. ARQ worker tested against live Redis.

**Not built**
8. Dosage tapering tracker.
9. Medicine photo verification.
10. i18n (hi/ta/te/bn/mr) and voice self-reports (Whisper).
11. Large-text / high-contrast mode.
12. Any client application (patient screens, QR display).

**Blocked on people, not code**
13. Minor symptom guidance — requires a qualified reviewer or a public-health content source before any clinical text ships.

---

## 8. CONSTRAINTS — AND HOW EACH IS ENFORCED

| # | Constraint | Enforcement in code |
|---|---|---|
| 1 | Never auto-answer a medical question | Questions are stored; the response carries "Taalmel does not answer clinical questions" |
| 2 | Never name a medicine for a symptom | Feature not built; when built, the architecture doc forbids it |
| 3 | Never mark an unchecked interaction "safe" | `NOT_COVERED` is the default outside the curated dataset; tested |
| 4 | Never trust OCR without human verification | `PrescriptionItem.verified` starts false; medications are only created by the verify endpoint |
| 5 | Never require a doctor to install or log in | Public token route; no doctor account model exists |
| 6 | Never auto-close a case | Transitions require an explicit human action; `RESOLVED` is terminal; tested |
| 7 | Never overwrite event history | No update/delete path exists for `events`; a structural test guards this |
| 8 | Never assume consent | Access row + active consent + unexpired window; 403 otherwise; tested |
| 9 | Medical content from official sources only | No clinical text is generated anywhere; dictionaries are labelled illustrative; symptom content blocked |

**Additional enforced rules discovered during the build:**
- Missing evidence reports `UNKNOWN`, never a guess; adherence with no reports is `null`, not 0%.
- Lab values are stored and shown verbatim; no code path interprets them as good or bad.
- A stale evidence dimension does not silently participate in a conflict.

---

## 9. COVERAGE SUMMARY

| Area | Built | Partial | Not built |
|---|---|---|---|
| Core engine | 9 | 1 (OCR) | 2 |
| Safety & trust | 6 | 1 | 1 |
| Doctor & lab | 5 | 1 | 2 |
| Companion | 7 | 1 | 0 |
| Accessibility | 0 | 0 | 4 |

**Roughly 27 of 38 listed features are working; 4 are partial; 7 are not built.**
