"""Longitudinal medication history.

The rest of the app answers "what is true today". This module answers the question a new
doctor actually asks: over the years, what was prescribed, at what dose, and when did it
change?

Nothing here is stored in a new table. Episodes are derived from verified prescription
items, so the append-only record stays the single source of truth and a corrected item
immediately corrects the history. Only human-verified items participate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlmodel import Session, select

from app.consent.service import authorize_patient
from app.db.models import Condition, Prescription, PrescriptionItem
from app.services.normalization import resolve_name


@dataclass
class _Entry:
    date: datetime | None
    written_name: str
    generic: str
    dose: str | None
    frequency: str | None
    instructions: str | None
    prescriber: str | None
    prescription_id: str
    filename: str
    created_at: datetime


@dataclass
class _Episode:
    dose: str | None
    frequency: str | None
    start: datetime | None
    end: datetime | None
    previous_dose: str | None = None
    sources: list[dict] = field(default_factory=list)


def _drug_key(written_name: str) -> tuple[str, str]:
    """(grouping key, display name). Dictionary agreement groups brand and generic."""
    resolution = resolve_name(written_name)
    if resolution.method != "UNRESOLVED" and resolution.generic_name:
        return f"g:{resolution.generic_name.lower()}", resolution.generic_name
    cleaned = " ".join(written_name.lower().split())
    return f"w:{cleaned}", written_name


def _iso(value: datetime | None) -> str | None:
    return value.date().isoformat() if value is not None else None



def medication_timeline(
    session: Session, *, user_id: str, patient_id: str, year: int | None = None
) -> dict:
    """Build a dated, per-drug history from verified items.

    Undated items are kept and reported as undated rather than placed in a guessed year.
    When `year` is given, undated items are excluded because they cannot be attributed.
    """
    patient = authorize_patient(session, user_id, patient_id)
    member_id = patient.household_member_id

    rows = session.exec(
        select(PrescriptionItem, Prescription)
        .join(Prescription, PrescriptionItem.prescription_id == Prescription.id)
        .where(
            Prescription.household_member_id == member_id,
            PrescriptionItem.verified == True,  # noqa: E712 - SQL comparison
        )
    ).all()

    entries: list[tuple[_Entry, str, str]] = []
    for item, prescription in rows:
        key, display = _drug_key(item.medication_name)
        date = prescription.prescribed_on
        entries.append(
            (
                _Entry(
                    date=date,
                    written_name=item.medication_name,
                    generic=display,
                    dose=item.dosage,
                    frequency=item.frequency,
                    instructions=item.instructions,
                    prescriber=prescription.prescribed_by,
                    prescription_id=prescription.id,
                    filename=prescription.original_filename,
                    created_at=prescription.created_at,
                ),
                key,
                display,
            )
        )

    if year is not None:
        entries = [
            (entry, key, display)
            for entry, key, display in entries
            if entry.date is not None and entry.date.year == year
        ]

    # Dated entries first, oldest to newest; undated last, in the order they were recorded.
    entries.sort(
        key=lambda row: (
            row[0].date is None,
            row[0].date or row[0].created_at,
            row[0].created_at,
        )
    )

    medications: dict[str, dict] = {}
    for entry, key, display in entries:
        group = medications.setdefault(
            key,
            {"generic": display, "written_names": [], "episodes": [], "sources": []},
        )
        if entry.written_name not in group["written_names"]:
            group["written_names"].append(entry.written_name)
        group["sources"].append(entry.prescription_id)

        episodes: list[_Episode] = group["episodes"]
        source = {
            "prescription_id": entry.prescription_id,
            "filename": entry.filename,
            "prescriber": entry.prescriber,
            "date": _iso(entry.date),
        }
        current = episodes[-1] if episodes else None
        same_dose = (
            current is not None
            and (current.dose or "").strip().lower() == (entry.dose or "").strip().lower()
            and (current.frequency or "").strip().lower()
            == (entry.frequency or "").strip().lower()
        )
        if current is not None and same_dose:
            current.end = entry.date or current.end
            current.sources.append(source)
            continue

        episodes.append(
            _Episode(
                dose=entry.dose,
                frequency=entry.frequency,
                start=entry.date,
                end=entry.date,
                previous_dose=current.dose if current is not None else None,
                sources=[source],
            )
        )

    condition_rows = session.exec(
        select(Condition)
        .where(Condition.household_member_id == member_id)
        .order_by(Condition.created_at)
    ).all()
    if year is not None:
        condition_rows = [
            condition
            for condition in condition_rows
            if condition.onset_date is not None and condition.onset_date.year == year
        ]

    visits: dict[str | None, dict] = {}
    for entry, _key, display in entries:
        bucket = visits.setdefault(
            _iso(entry.date),
            {
                "date": _iso(entry.date),
                "prescriber": entry.prescriber,
                "prescription_id": entry.prescription_id,
                "filename": entry.filename,
                "conditions": [],
                "medicines": [],
            },
        )
        bucket["medicines"].append(
            {
                "name": display,
                "written_name": entry.written_name,
                "dose": entry.dose,
                "frequency": entry.frequency,
            }
        )

    for condition in condition_rows:
        source_id = condition.source_prescription_id
        target = next(
            (
                bucket
                for bucket in visits.values()
                if source_id is not None and bucket["prescription_id"] == source_id
            ),
            None,
        )
        if target is None:
            bucket_key = _iso(condition.onset_date)
            target = visits.setdefault(
                bucket_key,
                {
                    "date": bucket_key,
                    "prescriber": None,
                    "prescription_id": source_id,
                    "filename": None,
                    "conditions": [],
                    "medicines": [],
                },
            )
        target["conditions"].append(
            {
                "id": condition.id,
                "name": condition.name,
                "name_raw": condition.name_raw,
                "confirmed": condition.confirmed,
                "status": condition.status,
            }
        )

    years: dict[str, list[dict]] = {}
    for bucket in sorted(
        visits.values(), key=lambda b: (b["date"] is None, b["date"] or "")
    ):
        label = bucket["date"][:4] if bucket["date"] else "date not recorded"
        years.setdefault(label, []).append(bucket)

    # A confirmed diagnosis is linked to the medicines on the prescription it was written
    # on. That is co-occurrence on one page, not a claim that the drug treated the
    # condition, so the basis is stated on every link.
    condition_links = []
    for condition in condition_rows:
        if not condition.confirmed:
            continue
        source = condition.source_prescription_id
        matching = [
            entry
            for entry, _key, _display in entries
            if source is not None and entry.prescription_id == source
        ]
        if not matching:
            continue
        medicines: list[dict] = []
        seen_names: set[str] = set()
        for entry in matching:
            if entry.generic.lower() in seen_names:
                continue
            seen_names.add(entry.generic.lower())
            medicines.append(
                {
                    "name": entry.generic,
                    "written_name": entry.written_name,
                    "dose": entry.dose,
                    "frequency": entry.frequency,
                }
            )
        condition_links.append(
            {
                "condition": {
                    "id": condition.id,
                    "name": condition.name,
                    "confirmed": True,
                },
                "date": _iso(matching[0].date) if matching else None,
                "prescription_id": source,
                "medicines": medicines,
                "basis": (
                    "Written on the same prescription page as these medicines. "
                    "Taalmel does not assert that a medicine treated the condition."
                ),
            }
        )

    return {
        "patient_id": patient_id,
        "year_filter": year,
        "years": [{"year": label, "visits": items} for label, items in years.items()],
        "medications": [
            {
                "generic": group["generic"],
                "written_names": group["written_names"],
                "prescription_count": len(set(group["sources"])),
                "episodes": [
                    {
                        "start": _iso(episode.start),
                        "end": _iso(episode.end),
                        "dose": episode.dose,
                        "frequency": episode.frequency,
                        "previous_dose": episode.previous_dose,
                        "dose_changed": episode.previous_dose is not None,
                        "sources": episode.sources,
                    }
                    for episode in group["episodes"]
                ],
            }
            for group in medications.values()
        ],
        "conditions": [
            {
                "id": condition.id,
                "name": condition.name,
                "name_raw": condition.name_raw,
                "confirmed": condition.confirmed,
                "status": condition.status,
                "date": _iso(condition.onset_date),
                "source_prescription_id": condition.source_prescription_id,
            }
            for condition in condition_rows
        ],
        "unconfirmed_conditions": sum(1 for c in condition_rows if not c.confirmed),
        "condition_links": condition_links,
        "note": (
            "Built from human-verified prescription lines only. Undated items are listed "
            "under 'date not recorded'. This is a record, not clinical advice."
        ),
    }
