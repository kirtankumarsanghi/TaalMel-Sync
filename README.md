# Taalmel Sync

Event-sourced medication reconciliation and follow-through backend for remote caregivers.

Core loop: **Prescribed → Observed → Reconciled → Why → Action → Resolved**

## Stack

Python 3.12 + FastAPI, SQLModel + SQLite (Postgres-ready), Alembic migrations.
See [`backend-py/README.md`](backend-py/README.md) for the full description.

> The original TypeScript prototype has been removed. It was superseded by the Python
> implementation, which re-implements the same domain; it is available in the git history
> if you need to refer back to it.

**Verified specification and feature status:** [`SPEC.md`](SPEC.md) — every status there was
checked against the code, not recalled. Read that before planning new work.

## Quick start

```bash
cd backend-py
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload     # http://127.0.0.1:8000/docs
```

Health check: `GET /health`

## Testing

```bash
cd backend-py
uv run pytest
```

The end-to-end core-loop scenario is `backend-py/tests/test_scenario_phase1.py`.

## Scope

The `future-work/` directory documents items that are deliberately **not** built and why —
most importantly minor-symptom guidance, which requires professional review of its clinical
content before any of it can ship.

## Non-negotiable design rules

- **Never write to `events` except through the event store.** That is what makes the audit
  trail a property of the data model rather than something to remember.
- **The state engine and conflict detector stay pure.** They read; they never mutate.
- **Never imply an untested medicine is safe.** Uncovered medicines must return
  `NOT_COVERED`, never be silently treated as fine.
- **Never generate medical content.** The system decides workflow; a human or an official
  source decides what the medical text says.
- **Nothing is silently dropped.** A failure is recorded and surfaced; a case stays open
  until someone resolves it.
