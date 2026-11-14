"""Pharmacy ordering behind a small provider interface.

No real pharmacy credentials ship with the project, so the default provider is a
deterministic mock that records a real order row and returns an acknowledgement. When
`TAALMEL_PHARMACY_API_URL` is set, the HTTP provider sends the same payload to that
endpoint. The rest of the system depends on the interface, not on a specific vendor.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings


@dataclass(frozen=True)
class PharmacyOrderResult:
    provider: str
    provider_order_id: str | None
    status: str
    detail: str | None = None


class PharmacyProvider:
    def create_order(self, patient_name: str, items: list[dict]) -> PharmacyOrderResult: ...


class MockPharmacyProvider:
    name = "mock"

    def create_order(self, patient_name: str, items: list[dict]) -> PharmacyOrderResult:
        return PharmacyOrderResult(
            provider=self.name,
            provider_order_id=None,
            status="READY_FOR_PHARMACY",
            detail=(
                "No pharmacy API is configured. The order is recorded so it can be "
                "handed to a pharmacist; nothing was transmitted."
            ),
        )


class HttpPharmacyProvider:
    name = "http"

    def __init__(self, url: str, api_key: str) -> None:
        self._url = url
        self._api_key = api_key

    def create_order(self, patient_name: str, items: list[dict]) -> PharmacyOrderResult:
        import httpx

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            response = httpx.post(
                self._url,
                json={"patient": patient_name, "items": items},
                headers=headers,
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json() if response.content else {}
            return PharmacyOrderResult(
                provider=self.name,
                provider_order_id=str(data.get("id") or data.get("order_id") or "") or None,
                status=str(data.get("status") or "SUBMITTED"),
                detail=data.get("detail"),
            )
        except Exception as exc:
            return PharmacyOrderResult(
                provider=self.name,
                provider_order_id=None,
                status="FAILED",
                detail=str(exc)[:300],
            )


def get_pharmacy_provider() -> PharmacyProvider:
    settings = get_settings()
    if settings.pharmacy_api_url:
        return HttpPharmacyProvider(settings.pharmacy_api_url, settings.pharmacy_api_key)
    return MockPharmacyProvider()
