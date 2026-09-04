-- Taalmel Sync — Core Schema
-- Implements the event-sourced model from Design Doc Section 5:
--   PATIENT -> MEDICATION -> EVIDENCE EVENTS -> DERIVED CURRENT STATE -> GAP/ISSUE -> REASON/ACTION/RESOLUTION
--
-- Principle: events are append-only and immutable. Nothing in `events` is ever
-- UPDATEd or DELETEd. All "current state" is derived by querying the event log
-- (see src/engines/medicationStateEngine.js). This file only creates tables;
-- it never encodes derived state as a column to be kept in sync by hand.

PRAGMA foreign_keys = ON;

-- ─────────────────────────────────────────────────────────────
-- Users & Households
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS users (
  id            TEXT PRIMARY KEY,
  role          TEXT NOT NULL CHECK (role IN ('caregiver', 'patient')),
  name          TEXT NOT NULL,
  phone         TEXT UNIQUE,
  password_hash TEXT NOT NULL,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS households (
  id         TEXT PRIMARY KEY,
  name       TEXT NOT NULL,
  created_by TEXT NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Section 3: MVP works with just Caregiver <-> Patient. Doctor is optional,
-- has no login, and only ever sees a generated export (Section 9.10).
CREATE TABLE IF NOT EXISTS household_members (
  id            TEXT PRIMARY KEY,
  household_id  TEXT NOT NULL REFERENCES households(id),
  user_id       TEXT REFERENCES users(id),          -- null if the patient has no login of their own
  display_name  TEXT NOT NULL,
  relationship  TEXT,                                 -- e.g. "Father", "Self"
  is_patient    INTEGER NOT NULL DEFAULT 1,            -- 9.11 ownership tagging target
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Access scoping (Section 11): caregiver sees only granted household members.
CREATE TABLE IF NOT EXISTS caregiver_access (
  id                    TEXT PRIMARY KEY,
  caregiver_user_id     TEXT NOT NULL REFERENCES users(id),
  household_member_id   TEXT NOT NULL REFERENCES household_members(id),
  granted_at            TEXT NOT NULL DEFAULT (datetime('now')),
  consent_recorded      INTEGER NOT NULL DEFAULT 0,     -- explicit consent, Section 11
  UNIQUE(caregiver_user_id, household_member_id)
);

-- ─────────────────────────────────────────────────────────────
-- Medications (identity only — NOT current status; status is derived)
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS medications (
  id                   TEXT PRIMARY KEY,
  household_member_id  TEXT NOT NULL REFERENCES household_members(id),
  name_raw             TEXT NOT NULL,       -- as extracted / entered
  name_generic         TEXT,                -- normalized brand -> generic (9.1)
  dose_raw             TEXT,
  identity_confirmed   INTEGER NOT NULL DEFAULT 0, -- barcode/OCR match, Section 7
  created_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────────────────────
-- Event Log — the source of truth (Section 5, Section 9.7/9.8)
-- ─────────────────────────────────────────────────────────────
-- event_type is one of the values in src/events/eventTypes.js:
--   PrescriptionUploaded, MedicationExtracted, MedicationReported,
--   AvailabilityObserved, MedicationConfirmed, ConflictDetected,
--   ReasonRecorded, ActionAssigned, CaseResolved, DoseChanged
--
-- payload is a JSON blob whose shape depends on event_type. Storing it as
-- JSON (rather than many nullable columns) keeps the log append-only and
-- lets new event types be added without a migration.

CREATE TABLE IF NOT EXISTS events (
  id            TEXT PRIMARY KEY,
  medication_id TEXT NOT NULL REFERENCES medications(id),
  event_type    TEXT NOT NULL,
  payload       TEXT NOT NULL,                 -- JSON.stringify'd
  source        TEXT NOT NULL,                 -- 'patient' | 'caregiver' | 'doctor' | 'ocr' | 'system'
  source_user_id TEXT REFERENCES users(id),
  occurred_at   TEXT NOT NULL DEFAULT (datetime('now')), -- when the fact became true
  recorded_at   TEXT NOT NULL DEFAULT (datetime('now'))  -- when Taalmel learned it (audit)
);

CREATE INDEX IF NOT EXISTS idx_events_medication ON events(medication_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);

-- ─────────────────────────────────────────────────────────────
-- Cases — the resolution-tracking centerpiece (Section 9.9)
-- ─────────────────────────────────────────────────────────────
-- A case is a first-class object with a lifecycle, not a one-shot alert.

CREATE TABLE IF NOT EXISTS cases (
  id             TEXT PRIMARY KEY,
  medication_id  TEXT NOT NULL REFERENCES medications(id),
  trigger_event_id TEXT REFERENCES events(id),   -- what opened this case (Section 4)
  reason_code    TEXT,                            -- Section 9.5 taxonomy, null until classified
  status         TEXT NOT NULL DEFAULT 'OPEN'
                 CHECK (status IN ('OPEN', 'AWAITING_INFO', 'RESOLVED', 'STILL_UNCERTAIN')),
  action_taken   TEXT,
  opened_at      TEXT NOT NULL DEFAULT (datetime('now')),
  resolved_at    TEXT,
  resolution_note TEXT
);

CREATE INDEX IF NOT EXISTS idx_cases_medication ON cases(medication_id);
CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status);

-- ─────────────────────────────────────────────────────────────
-- Ask-My-Doctor question capture (Section 9.13)
-- ─────────────────────────────────────────────────────────────
-- Deliberately NOT a chatbot log: capture-and-defer, never an answer.

CREATE TABLE IF NOT EXISTS doctor_questions (
  id             TEXT PRIMARY KEY,
  medication_id  TEXT REFERENCES medications(id),
  household_member_id TEXT NOT NULL REFERENCES household_members(id),
  question_text  TEXT NOT NULL,
  raised_by      TEXT NOT NULL,     -- 'patient' | 'caregiver'
  status         TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'DISCUSSED')),
  created_at     TEXT NOT NULL DEFAULT (datetime('now')),
  discussed_at   TEXT
);

-- ─────────────────────────────────────────────────────────────
-- Minor Symptom Guidance & Care Connector (Section 9.14)
-- ─────────────────────────────────────────────────────────────
-- FUTURE WORK per the design doc — table exists so the event-logging
-- architecture can be demoed, but the actual clinical content
-- (self-limiting symptom list, red-flag thresholds) is NOT implemented
-- here. See future-work/minor-symptom-guidance/ARCHITECTURE.md.

CREATE TABLE IF NOT EXISTS symptom_checks (
  id                  TEXT PRIMARY KEY,
  household_member_id TEXT NOT NULL REFERENCES household_members(id),
  symptom_text        TEXT NOT NULL,
  red_flag_matched    INTEGER,                 -- 1/0/null — null means "not evaluated, demo stub only"
  outcome             TEXT,                    -- 'ESCALATE' | 'SELF_CARE_INFO' | 'NOT_EVALUATED'
  source_reference    TEXT,                    -- named official source, if any
  created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
