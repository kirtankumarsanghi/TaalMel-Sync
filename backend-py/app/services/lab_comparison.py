"""Compare the same lab test across reports.

This is arithmetic, not interpretation. A value is compared with the reference range
that was printed on its own report, and with the same test on earlier dates. When a
report prints no numeric range, or the result is qualitative ("Negative"), the
comparison is `NOT_COMPARABLE` — the app never guesses what normal means.

Units are part of the grouping key: 1.2 mg/dL and 1.2 mmol/L are not the same series.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.consent.service import authorize_patient
from app.db.models import LabReport, LabValue

_NUMERIC = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
_RANGE_SEP = re.compile(r"\s*(?:-|–|—|to)\s*")
_QUALIFIER = re.compile(r"\([^)]*\)")


@dataclass
class _Point:
    date: datetime
    value_raw: str
    value: float | None
    unit: str | None
    range_low: float | None
    range_high: float | None
    status: str


@dataclass
class _Series:
    name: str
    unit: str | None
    points: list[_Point] = field(default_factory=list)


def canonical_test_name(name: str) -> str:
    """A stable grouping key. Parenthetical qualifiers and punctuation are dropped."""
    cleaned = _QUALIFIER.sub(" ", name or "")
    cleaned = cleaned.replace("%", " ")
    cleaned = re.sub(r"[^A-Za-z0-9 ]+", " ", cleaned)
    return " ".join(cleaned.lower().split())


def parse_numeric(raw: str | None) -> float | None:
    """Parse a printed value. Returns None for qualitative results."""
    if not raw:
        return None
    text = raw.strip().replace(",", "")
    # "1,20,000" style grouping would already be lost; take the leading number only.
    match = _NUMERIC.search(text)
    if match is None:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def parse_reference_range(raw: str | None) -> tuple[float | None, float | None]:
    """Parse "4.0 - 5.6", "0.7–1.3", "< 5", "> 30". Anything else is unknown."""
    if not raw:
        return (None, None)
    text = raw.strip().replace(",", "")
    lowered = text.lower()

    upper_only = re.match(r"^\s*(?:<|<=|upto|up to|less than)\s*([-+]?\d+(?:\.\d+)?)", lowered)
    if upper_only:
        return (None, float(upper_only.group(1)))

    lower_only = re.match(r"^\s*(?:>|>=|greater than|more than)\s*([-+]?\d+(?:\.\d+)?)", lowered)
    if lower_only:
        return (float(lower_only.group(1)), None)

    parts = _RANGE_SEP.split(text)
    if len(parts) >= 2:
        low = parse_numeric(parts[0])
        high = parse_numeric(parts[1])
        if low is not None and high is not None:
            return (low, high)
    return (None, None)


def compare_to_range(
    value: float | None, low: float | None, high: float | None
) -> str:
    """Factual position against the report's own printed range."""
    if value is None or (low is None and high is None):
        return "NOT_COMPARABLE"
    if low is not None and value < low:
        return "BELOW"
    if high is not None and value > high:
        return "ABOVE"
    return "WITHIN"


def _report_date(report: LabReport) -> datetime:
    if report.captured_on:
        try:
            return datetime.fromisoformat(report.captured_on).replace(tzinfo=UTC)
        except ValueError:
            pass
    created = report.created_at
    return created if created.tzinfo else created.replace(tzinfo=UTC)


def _unit_key(unit: str | None) -> str:
    return (unit or "").strip().lower()


def lab_comparison(session: Session, *, user_id: str, patient_id: str) -> dict:
    patient = authorize_patient(session, user_id, patient_id)
    member_id = patient.household_member_id

    rows = session.exec(
        select(LabValue, LabReport)
        .join(LabReport, LabValue.lab_report_id == LabReport.id)
        .where(
            LabReport.household_member_id == member_id,
            LabReport.ocr_status.in_(["COMPLETED", "NEEDS_REVIEW"]),  # type: ignore[attr-defined]
        )
    ).all()

    series: dict[tuple[str, str], _Series] = {}
    for value, report in rows:
        key = (canonical_test_name(value.test_name), _unit_key(value.unit))
        group = series.setdefault(key, _Series(name=value.test_name.strip(), unit=value.unit))
        numeric = parse_numeric(value.value)
        low, high = parse_reference_range(value.reference_range_raw)
        group.points.append(
            _Point(
                date=_report_date(report),
                value_raw=value.value,
                value=numeric,
                unit=value.unit,
                range_low=low,
                range_high=high,
                status=compare_to_range(numeric, low, high),
            )
        )

    tests = []
    for group in series.values():
        points = sorted(group.points, key=lambda point: point.date)
        numeric_points = [point for point in points if point.value is not None]
        latest = numeric_points[-1] if numeric_points else None
        first = numeric_points[0] if numeric_points else None

        trend = None
        change = None
        if latest is not None and first is not None and latest is not first:
            change = round(latest.value - first.value, 4)
            trend = "UP" if change > 0 else "DOWN" if change < 0 else "SAME"

        tests.append(
            {
                "test_name": group.name,
                "unit": group.unit,
                "latest_value": latest.value_raw if latest else None,
                "latest_date": latest.date.date().isoformat() if latest else None,
                "latest_status": latest.status if latest else "NOT_COMPARABLE",
                "earliest_value": first.value_raw if first else None,
                "earliest_date": first.date.date().isoformat() if first else None,
                "change": change,
                "trend": trend,
                "comparable_points": len(numeric_points),
                "points": [
                    {
                        "date": point.date.date().isoformat(),
                        "value_raw": point.value_raw,
                        "value": point.value,
                        "range_low": point.range_low,
                        "range_high": point.range_high,
                        "status": point.status,
                    }
                    for point in points
                ],
            }
        )

    tests.sort(key=lambda test: test["test_name"].lower())
    above = sum(1 for test in tests if test["latest_status"] == "ABOVE")
    below = sum(1 for test in tests if test["latest_status"] == "BELOW")
    within = sum(1 for test in tests if test["latest_status"] == "WITHIN")

    return {
        "patient_id": patient_id,
        "tests": tests,
        "summary": {"above": above, "below": below, "within": within},
        "note": (
            "Status compares each value with the reference range printed on the same "
            "report. It is not a diagnosis and does not say whether a value is healthy. "
            "Comparisons are made only between identical units."
        ),
    }
