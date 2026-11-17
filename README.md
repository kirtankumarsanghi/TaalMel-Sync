# Taalmel Sync

Taalmel Sync is an event-sourced medication reconciliation and follow-through system for
families managing an elderly or chronically ill patient's medicines remotely.

It answers three questions a caregiver actually has:

1. **What is supposed to be happening?** — from the prescription.
2. **What is actually happening?** — from self-reports, physical stock checks, and status confirmations.
3. **What should happen next?** — a tracked case, a reason, an action, and a doctor-ready record.

The core loop is:

```
PRESCRIBED → OBSERVED → RECONCILED → WHY → ACTION → RESOLVED
```

Taalmel does not diagnose, prescribe, or give medical advice. It records evidence, finds
disagreements, routes them to a person, and keeps the history intact.

---

## What this repository contains

```
Taalmel Sync/
  backend-py/        FastAPI backend, SQLModel, Alembic, OCR, ARQ worker, tests
  frontend/          React + TypeScript + Vite client
  future-work/       Deliberately deferred clinical / product work
  SPEC.md            Detailed, feature-by-feature implementation status
  README.md          This file
```

The original TypeScript prototype was removed; the Python backend is the source of truth.

---

## Current status

**Backend:** 410 passing tests. Alembic migrations are reversible and tested against the
model schema.

**Frontend:** production build passes. A real-browser Playwright flow covers signup,
consent, onboarding, prescription upload, verification, evidence, conflict, reason,
resolution, doctor link, QR rendering, safety, wellness, lab upload, language, and
accessibility toggles: **16/16 checks pass with no console errors**.

### Working end to end

- Prescription upload, OCR, human verification, medication creation.
- PDF prescriptions and lab reports: embedded text is read directly, not rasterized.
- Lab report parsing with units, ranges, and qualitative results.
- Append-only event log, four-dimension medication state, per-dimension freshness.
- Conflict detection: prescription vs report, report vs availability, stopped but
  unexplained, expired stock.
- Eight reason codes, executed actions, case lifecycle, resolution tracking.
- Trigger rules, notification rows, webhook/SMTP delivery when configured.
- Expiry warnings and expired-stock cases, including a daily ARQ cron.
- Drug interaction / duplicate-ingredient check over a curated dataset.
- Doctor export: JSON, PDF, print-ready HTML, QR, short-lived public link with no login.
- Prescriber name/date, sourced timeline, lab correlation, minimal info card.
- Companion views: today, what changed, Ask My Doctor, refill list, completeness.
- Taper schedule tracking, photo label OCR, emergency contacts (API).
- Optional doctor account/dashboard; public links still require no account.
- English, Hindi, Tamil, Telugu, Bengali, Marathi interface strings.
- Browser voice reports via Web Speech API, or server audio via optional Whisper.
- Large-text and high-contrast modes.
- Offline evidence outbox with idempotent replay.
- Pharmacy refill ordering through a provider interface; local mock by default.
- Unified document intake for prescriptions, lab reports, discharge summaries, invoices,
  and unknown pages.
- Longitudinal history: verified prescription lines are merged per drug across years,
  with dated dose changes and the source document on every episode. Diagnoses labelled
  "Dx"/"Diagnosis" are captured, held unconfirmed until a person confirms them, and can
  be added by hand.
- Lab comparison: each test tracked across reports and compared with the reference range
  printed on its own report. Different units stay separate; qualitative results are not
  compared. No clinical judgement is produced.
- Multi-year dossier: one PDF with conditions, medicines by year, dose-change log, lab
  comparison, sources, and the records that could not be read.
- Bulk archive import: many files at once, one visit date each, with per-file results.

### Partial / external

- **Handwriting OCR:** EasyOCR, TrOCR, and the Windows OCR engine cannot read many Indian
  doctor cursive pages. Automatic handwriting requires a vision-capable cloud key
  (Gemini or Google Cloud Vision). Without it, the app preserves the raw OCR, opens a
  manual review, and supports paste-to-parse. No result is auto-verified.
- **Plain-language explanation:** the doctor's instruction is shown verbatim; no generated
  lay explanation exists.
- **Interaction dataset:** honest `NOT_COVERED`, but only a small curated dataset.
- **Lab extraction:** real OCR path, but extraction quality depends on the document.
- **Symptom guidance:** implemented as a care connector (record + severity routing), not
  clinical triage. Clinical content is intentionally blocked pending review.
- **Offline-first:** writes queue and replay; reads still need connectivity.
- **Pharmacy:** real provider interface, but actual transmission needs credentials.
- **Access management UI:** temporary handoff, consent revocation, and emergency contacts
  have working API endpoints but no caregiver screen yet.

### Not built

- PaddleOCR fallback.
- Full clinical symptom guidance.
- Hospital integration / MCP.
- Image-similarity medicine verification (the current check is label-text OCR).

---

## Architecture

```
React client (Vite)
        │  /api
        ▼
FastAPI routers
        │
        ├── Auth / consent / audit
        ├── Prescriptions + document intake
        ├── Evidence capture
        ├── Reconciliation engines (pure logic)
        ├── Cases / reasons / triggers
        ├── Doctor export / QR / lab correlation
        └── Companion / wellness / refill
        │
        ▼
SQLModel + SQLite (Postgres-ready)
        │
        ├── append-only events
        ├── medications / cases / conflicts
        ├── prescriptions / lab reports
        └── documents / access / audit
```

Background OCR and the daily expiry/refill sweep use **ARQ + Redis** in deployment and an
inline queue in development.

### Core design rules

- **Events are append-only.** There is no update or delete path for `events`; corrections
  are new events.
- **Engines are pure.** State, conflicts, cases, reasons, and trigger rules read inputs and
  return results; persistence lives in services.
- **Missing evidence is `UNKNOWN`.** It is never guessed. Adherence with no reports is
  `null`, not `0%`.
- **Nothing is auto-verified.** OCR creates review items, not medications. A person confirms.
- **No medical content is generated.** The app records workflow and routes to professionals.
- **Cases do not auto-close.** A person resolves them.
- **Nothing is silently dropped.** Failures are recorded and surfaced.

---

## Tech stack

| Layer | Used |
|---|---|
| Language | Python 3.12 |
| API | FastAPI |
| Validation | Pydantic v2 |
| ORM / DB | SQLModel + SQLAlchemy 2.x, SQLite (Postgres via compose) |
| Migrations | Alembic (9 revisions) |
| Auth | PyJWT + argon2id (deliberate deviations from python-jose/passlib) |
| Rate limiting | slowapi (in-memory) |
| Background jobs | ARQ + Redis, inline fallback |
| OCR | EasyOCR, PyMuPDF text layer, optional Google Vision / Gemini / TrOCR |
| PDF export | fpdf2 |
| QR | qrcode |
| Logging | structlog |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS |
| Tests | pytest, FastAPI TestClient, Playwright |

---

## Quick start

### Requirements

- Python **3.12+**
- [uv](https://docs.astral.sh/uv/)
- Node.js 20+ and npm

### 1. Backend

```bash
cd backend-py
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8010
```

If you are using the existing virtualenv:

```bash
cd backend-py
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8010
```

- API: `http://127.0.0.1:8010`
- Swagger: `http://127.0.0.1:8010/docs`
- Health: `http://127.0.0.1:8010/health`

### 2. Frontend

```bash
cd frontend
npm install --include=dev
npm run dev
```

Open `http://127.0.0.1:5173`.

The Vite dev server proxies `/api` to `http://127.0.0.1:8010`. Keep the backend on **8010**
unless you change `frontend/vite.config.ts`.

---

## Configuration

Copy `backend-py/.env.example` to `backend-py/.env` and edit as needed.

```env
TAALMEL_DATABASE_URL=sqlite:///data/taalmel.db
TAALMEL_JWT_SECRET=change-me
TAALMEL_JOB_QUEUE=inline
TAALMEL_OCR_ENGINE=auto
```

### OCR / handwriting

`auto` chooses the best configured provider:

1. Google Cloud Vision if `TAALMEL_GOOGLE_VISION_API_KEY` is set
2. Gemini if `TAALMEL_GEMINI_API_KEY` is set
3. EasyOCR if installed
4. deterministic stub

For handwritten Indian prescriptions:

```env
# Option A — Google AI Studio Gemini key (free tier, no billing account)
TAALMEL_OCR_ENGINE=gemini
TAALMEL_GEMINI_API_KEY=AIza...
TAALMEL_GEMINI_MODEL=gemini-2.5-flash
```

```env
# Option B — Google Cloud Vision (billing account required, free monthly tier)
TAALMEL_OCR_ENGINE=google
TAALMEL_GOOGLE_VISION_API_KEY=...
```

```bash
# Option C — local TrOCR (experimental; poor on many cursive pages)
uv sync --extra handwriting
TAALMEL_OCR_ENGINE=trocr
```

Without a cloud key, handwritten pages still open in the review screen with the raw OCR
and manual/paste-text entry. That is deliberate: a wrong auto-created medicine is worse
than an honest "could not read this".

### Notifications

Rows are always written. To actually deliver them, configure either:

```env
TAALMEL_NOTIFICATION_WEBHOOK_URL=
TAALMEL_NOTIFICATION_WEBHOOK_TOKEN=
```

or SMTP:

```env
TAALMEL_SMTP_HOST=
TAALMEL_SMTP_PORT=587
TAALMEL_SMTP_USERNAME=
TAALMEL_SMTP_PASSWORD=
TAALMEL_SMTP_FROM=
```

If neither is configured, the notification row records
`delivery_error="no delivery channel configured"`.

### Pharmacy

```env
TAALMEL_PHARMACY_API_URL=
TAALMEL_PHARMACY_API_KEY=
```

With no URL, the mock provider records the refill order locally for a pharmacist.

---

## Testing

### Backend

```bash
cd backend-py
uv run pytest
```

- 385 tests
- Includes migration/model drift checks and an end-to-end core-loop scenario
- `tests/test_product_completion.py` covers the documented API aliases and completion work

### Frontend

```bash
cd frontend
npm run build
node scripts/check-ui.mjs
node scripts/check-features.mjs
node scripts/check-history.mjs
```

The feature check drives the real app: signup, consent, onboarding, upload, OCR,
verification, evidence, conflict, reason, resolution, doctor link, QR, safety, wellness,
lab upload, language, large text, and high contrast.

---

## Main API groups

All private routes require a bearer access token and consent-based household access.
The public doctor route is token-only.

- **Auth:** register, login, refresh, logout, me
- **Households/patients:** create household, add patient, get/update patient, access/consent
- **Prescriptions:** upload, get, patch prescriber, verify, manual item, parse pasted text
- **Documents:** unified upload, list, reclassify as prescription
- **Evidence:** report, availability, confirm, dose change, history, state
- **Cases:** detect, open cases, reason, action, resolve, explain
- **Triggers:** notifications, mark read, run checks
- **Doctor export:** JSON/PDF/HTML, link, QR, public token view, optional doctor dashboard
- **Lab:** upload, correlation, patient-level list/timeline
- **Companion:** today, changes, questions, completeness, summary, refill list/order
- **History:** medication timeline by year, dose-change episodes, conditions (list/add/confirm)
- **Voice/symptoms/wellness:** transcript or audio report, symptom connector, timeline
- **i18n:** language list, catalogue, single string

See `SPEC.md §5` for the full route list and exact statuses.

---

## Feature status document

`SPEC.md` is the detailed implementation status, including:

- tech-stack verification
- feature-by-feature status
- workflow integrity
- safety constraints
- API reference
- coverage summary

Read it before planning new work. It intentionally states what is partial instead of
rounding up.

---

## Safety and privacy

- This is not a diagnostic or prescribing tool.
- All OCR output requires human verification before it becomes a medication.
- Medical content is not generated by an LLM.
- Uploaded files contain personal health information; `backend-py/data/uploads/` is
  gitignored. Do not commit that directory.
- Cloud OCR sends the uploaded document to the configured provider. Obtain consent before
  enabling it.
- Replace `TAALMEL_JWT_SECRET` before any real deployment.
