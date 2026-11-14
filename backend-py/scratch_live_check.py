import uuid

import httpx
import pymupdf

base = "http://127.0.0.1:8010"
phone = "9" + str(uuid.uuid4().int)[:11]

doc = pymupdf.open()
page = doc.new_page()
for i, line in enumerate(
    [
        "CITY MEDICAL CENTRE",
        "Dr. A. Rao",
        "Rx",
        "Tab Metformin 500mg BD",
        "Tab Amlodipine 5mg OD",
    ]
):
    page.insert_text((50, 60 + i * 32), line, fontsize=16)
pdf = doc.tobytes()
doc.close()

with httpx.Client(base_url=base, timeout=180) as c:
    r = c.post(
        "/api/auth/register",
        json={
            "name": "Test",
            "phone": phone,
            "password": "correct-horse-battery",
            "role": "caregiver",
        },
    )
    print("register", r.status_code, r.text[:300])
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    r = c.post(
        "/api/households",
        headers=headers,
        json={
            "household_name": "T",
            "patient_display_name": "P",
            "consent_recorded": True,
        },
    )
    print("household", r.status_code, r.text[:300])
    member = r.json()["patient"]["household_member_id"]

    r = c.post(
        "/api/documents/upload",
        headers=headers,
        params={"household_member_id": member},
        files={"file": ("rx.pdf", pdf, "application/pdf")},
    )
    print("upload", r.status_code, r.text[:2000])
    if r.status_code == 201:
        body = r.json()
        if body.get("prescription_id"):
            r2 = c.get(f"/api/prescriptions/{body['prescription_id']}", headers=headers)
            print("prescription", r2.status_code, r2.text[:2000])
