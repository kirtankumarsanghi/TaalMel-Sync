"""Drug-interaction and duplicate-ingredient check over a small curated dataset.

The dataset is illustrative and explicitly incomplete. The rule that matters:
a medicine outside the dataset yields NOT_COVERED. It is never reported as safe.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from app.services.normalization import resolve_name

DATASET_PATH = Path(__file__).resolve().parent.parent / "data" / "safety-interactions.json"

PairResult = Literal[
    "INTERACTION_FLAGGED", "DUPLICATE_INGREDIENT_FLAGGED", "NO_KNOWN_ISSUE_IN_DATASET", "NOT_COVERED"
]

DISCLAIMER = (
    "This checks against a small, curated, referenced demonstration dataset only. "
    "It does not provide comprehensive clinical coverage. Medicines outside the dataset "
    "return NOT_COVERED and must never be read as 'confirmed safe.'"
)


@dataclass(frozen=True)
class Dataset:
    known: frozenset[str]
    interactions: tuple[dict, ...]
    duplicate_groups: tuple[tuple[str, ...], ...]


@lru_cache(maxsize=1)
def load_dataset() -> Dataset:
    raw = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    return Dataset(
        known=frozenset(m.lower() for m in raw["knownMedications"]),
        interactions=tuple(raw["interactions"]),
        duplicate_groups=tuple(tuple(g) for g in raw["duplicateIngredientGroups"]),
    )


@dataclass(frozen=True)
class PairCheck:
    a: str
    b: str
    result: PairResult
    detail: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class SafetyResult:
    normalized_names: tuple[str, ...]
    pairs: tuple[PairCheck, ...]
    uncovered: tuple[str, ...]
    disclaimer: str


def _to_generic(name: str) -> str:
    resolved = resolve_name(name)
    return resolved.generic_name or name


def check_interactions(names: list[str]) -> SafetyResult:
    dataset = load_dataset()
    generics = [_to_generic(n) for n in names]
    uncovered = tuple(n for n in generics if n.lower() not in dataset.known)

    pairs: list[PairCheck] = []
    for i in range(len(generics)):
        for j in range(i + 1, len(generics)):
            a, b = generics[i], generics[j]
            al, bl = a.lower(), b.lower()
            if al not in dataset.known or bl not in dataset.known:
                pairs.append(PairCheck(a=a, b=b, result="NOT_COVERED"))
                continue

            rule = next(
                (
                    r
                    for r in dataset.interactions
                    if {r["a"].lower(), r["b"].lower()} == {al, bl}
                ),
                None,
            )
            duplicate = any(
                {al, bl} <= {x.lower() for x in group} for group in dataset.duplicate_groups
            )

            if rule is not None:
                pairs.append(
                    PairCheck(a=a, b=b, result="INTERACTION_FLAGGED", detail=rule["note"], source=rule["source"])
                )
            elif duplicate:
                pairs.append(PairCheck(a=a, b=b, result="DUPLICATE_INGREDIENT_FLAGGED"))
            else:
                pairs.append(PairCheck(a=a, b=b, result="NO_KNOWN_ISSUE_IN_DATASET"))

    return SafetyResult(
        normalized_names=tuple(generics),
        pairs=tuple(pairs),
        uncovered=uncovered,
        disclaimer=DISCLAIMER,
    )
