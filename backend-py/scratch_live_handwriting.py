import uuid
from pathlib import Path

import httpx

image = Path(
    "data/uploads/prescriptions/8bae7104-2d41-496f-827e-827fdcc59ab0/"
    "3d544fb8170a84c92737f268f97e83ad65409da7996c168006282208757d11dc-"
    "WhatsApp_Image_2026-10-20_at_11.41.32_PM.jpeg"
).read_bytes()

base = "http://127.0.0.1:8010"
phone = "9" + str(uuid.uuid4().int)[:11]
with httpx.Client(base_url=base, timeout=240) as c:
    reg = c.post(
        "/api/auth/register",
        json={"name": "Hand", "phone": phone, "password": "correct-horse-battery", "role": "caregiver"},
    )
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    house = c.post(
        "/api/households",
        headers=headers,
        json={"household_name": "H", "patient_display_name": "P", "consent_recorded": True},
    )
    member = house.json()["patient"]["household_member_id"]
    up = c.post(
        "/api/documents/upload",
        headers=headers,
        params={"household_member_id": member},
        files={"file": ("kamakshi.jpg", image, "image/jpeg")},
    )
    print("upload", up.status_code, up.text[:1200])
    if up.status_code == 201:
        body = up.json()
        opened = c.post(f"/api/documents/{body['document_id']}/as-prescription", headers=headers)
        print("as-prescription", opened.status_code, opened.text[:400])
