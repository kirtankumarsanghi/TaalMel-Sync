"""Pull diagnoses off a prescription page.

A prescription usually states its diagnosis once, near the top: "Dx Acne grade III",
"Diagnosis: Acute gastroenteritis". This module only recognises that explicit label. It
does not infer a condition from a medicine name, and it keeps the raw wording so a
person can correct it before it is used to group anything.
"""

from __future__ import annotations

import re

# "Dx", "D/X", "Diagnosis", "Dx:" — the label must introduce the line.
_LABEL = re.compile(r"^\s*(?:d\s*[/x]\s*x?\s*|dx\.?|diagnosis)\s*[:.\-–]?\s*", re.IGNORECASE)

# Lines that carry a condition-like word but are advice or investigations.
_NOT_DIAGNOSIS = re.compile(
    r"\b(advice|adv\b|follow\s*-?\s*up|review|investigation|test|profile|"
    r"lft|kft|cbc|lipid|renal|thyroid|x-?ray|scan|signature|signed)\b",
    re.IGNORECASE,
)

# Separators between two named conditions on one line.
_SPLIT = re.compile(r"\s*(?:&|\+|;|\band\b)\s*", re.IGNORECASE)

MAX_CONDITIONS = 6


def diagnoses_from_text(raw_text: str) -> list[str]:
    """Return the diagnoses explicitly labelled on the page, in reading order.

    Conservative by design: an unlabelled line is not treated as a diagnosis, because a
    wrong problem list is worse than an empty one.
    """
    if not raw_text or not raw_text.strip():
        return []

    found: list[str] = []
    seen: set[str] = set()
    for line in raw_text.splitlines():
        match = _LABEL.match(line)
        if match is None:
            continue
        body = line[match.end():].strip()
        if not body or not any(ch.isalpha() for ch in body):
            continue
        if _NOT_DIAGNOSIS.search(body):
            continue

        for part in _SPLIT.split(body):
            cleaned = re.sub(r"[\s.,;:]+", " ", part).strip(" -–—")
            if len(cleaned) < 3 or not any(ch.isalpha() for ch in cleaned):
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(cleaned[:120])
            if len(found) >= MAX_CONDITIONS:
                return found
    return found
