"""Reason classification: what the caregiver said is the real reason, and what happens next.

The policy below is the reviewed table from reasonClassification.ts, unchanged in meaning.
Each action name maps to a concrete effect in app/services/reasons.py, so the policy
is executed, not only described.

Guardrails:
- SIDE_EFFECT is recorded as-is and routed to a professional. Nothing here interprets symptoms.
- COULD_NOT_AFFORD never ends at "here is a cheaper option". It points to resources and
  asks for a conversation with a doctor or pharmacist.
- PATIENT_DECLINED is recorded without judgement and never overridden.
- EXPIRED is a tracked case. It stays open until someone resolves it.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.events.types import ReasonCode


class ReasonAction(StrEnum):
    SHOW_INSTRUCTION_SIDE_BY_SIDE = "SHOW_INSTRUCTION_SIDE_BY_SIDE"
    OPEN_CASE_NOTIFY_CAREGIVER = "OPEN_CASE_NOTIFY_CAREGIVER"
    INCREASE_REMINDERS = "INCREASE_REMINDERS"
    SHOW_AFFORDABILITY_RESOURCES = "SHOW_AFFORDABILITY_RESOURCES"
    MARK_DISCONTINUED_CONFIRMED = "MARK_DISCONTINUED_CONFIRMED"
    ROUTE_TO_PROFESSIONAL_FOLLOWUP = "ROUTE_TO_PROFESSIONAL_FOLLOWUP"
    ROUTE_FOR_AWARENESS_NO_OVERRIDE = "ROUTE_FOR_AWARENESS_NO_OVERRIDE"


@dataclass(frozen=True)
class ReasonPolicy:
    action: ReasonAction
    description: str
    closes_case: bool


POLICY: dict[ReasonCode, ReasonPolicy] = {
    ReasonCode.CONFUSED_ABOUT_DOSE: ReasonPolicy(
        action=ReasonAction.SHOW_INSTRUCTION_SIDE_BY_SIDE,
        description=(
            "Show the original instruction and a plain-language explanation with its source, "
            "side by side, plus 'confirm with your doctor or pharmacist if unclear.'"
        ),
        closes_case=False,
    ),
    ReasonCode.RAN_OUT: ReasonPolicy(
        action=ReasonAction.OPEN_CASE_NOTIFY_CAREGIVER,
        description="Notify the caregiver and keep the case open until it is resolved.",
        closes_case=False,
    ),
    ReasonCode.FORGOT: ReasonPolicy(
        action=ReasonAction.INCREASE_REMINDERS,
        description="Increase reminder frequency and share reminders with the caregiver.",
        closes_case=True,
    ),
    ReasonCode.COULD_NOT_AFFORD: ReasonPolicy(
        action=ReasonAction.SHOW_AFFORDABILITY_RESOURCES,
        description=(
            "Show public affordability resources, then prompt a conversation with a doctor or "
            "pharmacist about alternatives. Never end at 'here is a cheaper option.'"
        ),
        closes_case=False,
    ),
    ReasonCode.DOCTOR_TOLD_TO_STOP: ReasonPolicy(
        action=ReasonAction.MARK_DISCONTINUED_CONFIRMED,
        description="Record a confirmed discontinuation and close the case.",
        closes_case=True,
    ),
    ReasonCode.SIDE_EFFECT: ReasonPolicy(
        action=ReasonAction.ROUTE_TO_PROFESSIONAL_FOLLOWUP,
        description=(
            "Recorded as reported. No symptom interpretation. Routed as "
            "'follow-up with a healthcare professional recommended.'"
        ),
        closes_case=False,
    ),
    ReasonCode.PATIENT_DECLINED: ReasonPolicy(
        action=ReasonAction.ROUTE_FOR_AWARENESS_NO_OVERRIDE,
        description=(
            "Recorded without judgement. Routed for caregiver awareness and, if relevant, "
            "a doctor conversation. Never overridden or pressured."
        ),
        closes_case=False,
    ),
    ReasonCode.EXPIRED: ReasonPolicy(
        action=ReasonAction.OPEN_CASE_NOTIFY_CAREGIVER,
        description=(
            "The medicine is past its expiry date. Notify the caregiver and keep the case "
            "open until a replacement is confirmed or the stock is removed."
        ),
        closes_case=False,
    ),
}


REPEAT_THRESHOLD = 3


def policy_for(code: ReasonCode) -> ReasonPolicy:
    return POLICY[code]
