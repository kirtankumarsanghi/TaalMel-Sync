import uuid
from pathlib import Path

import httpx

pdf = Path(
    "data/uploads/prescriptions/c8b3e33c-fb78-4f70-8490-4385c900a6f2/"
    "927d3ce3d676577f629d3163d53597cb5fa48eac840517cd5af7492b3a77f004-Kirtan_report.pdf"
).read_bytes()

base = "http://127.0.0.1:8010"
phone = "9" + str(uuid.uuid4().int)[:11]
with httpx.Client(base_url=base, timeout=180) as c:
    reg = c.post(
        "/api/auth/register",
        json={"name": "Report", "phone": phone, "password": "correct-horse-battery", "role": "caregiver"},
    )
    print("register", reg.status_code, reg.text[:200])
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    house = c.post(
        "/api/households",
        headers=headers,
        json={"household_name": "R", "patient_display_name": "P", "consent_recorded": True},
    )
    member = house.json()["patient"]["household_member_id"]
    up = c.post(
        "/api/documents/upload",
        headers=headers,
        params={"household_member_id": member},
        files={"file": ("report.pdf", pdf, "application/pdf")},
    )
    print("upload", up.status_code, up.text[:2000])
