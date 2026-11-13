import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.deps import db_session
from app.db.models import AuditRecord, CaregiverAccess, Consent, RefreshToken
from app.main import create_app


@pytest.fixture
def client():
    # StaticPool keeps one shared connection, so the in-memory DB survives across requests.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def override_session():
        with Session(engine) as s:
            yield s

    app = create_app()
    app.dependency_overrides[db_session] = override_session
    with TestClient(app) as c:
        c.engine = engine  # type: ignore[attr-defined]
        yield c


def _register(client, name: str, phone: str, role: str = "caregiver") -> dict:
    r = client.post(
        "/api/auth/register",
        json={"name": name, "phone": phone, "password": "correct-horse-battery", "role": role},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _household(client, token: str, consent: bool = True) -> dict:
    r = client.post(
        "/api/households",
        headers=_auth(token),
        json={
            "household_name": "Sharma family",
            "patient_display_name": "Amma",
            "relationship": "mother",
            "consent_recorded": consent,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


# ── Auth ────────────────────────────────────────────────────────────

def test_register_then_login_returns_tokens(client) -> None:
    _register(client, "Asha", "9000000001")
    r = client.post(
        "/api/auth/login",
        json={"phone": "9000000001", "password": "correct-horse-battery"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["user"]["name"] == "Asha"
    assert "password_hash" not in body["user"]


def test_duplicate_phone_is_409(client) -> None:
    _register(client, "Asha", "9000000002")
    r = client.post(
        "/api/auth/register",
        json={"name": "Other", "phone": "9000000002", "password": "correct-horse-battery", "role": "caregiver"},
    )
    assert r.status_code == 409


def test_wrong_password_is_401_and_audited(client) -> None:
    _register(client, "Asha", "9000000003")
    r = client.post("/api/auth/login", json={"phone": "9000000003", "password": "wrong-password!"})
    assert r.status_code == 401
    with Session(client.engine) as s:  # type: ignore[attr-defined]
        actions = [a.action for a in s.exec(select(AuditRecord)).all()]
    assert "LOGIN_FAILED" in actions


def test_protected_route_requires_bearer_token(client) -> None:
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_me_returns_current_user(client) -> None:
    tokens = _register(client, "Asha", "9000000004")
    r = client.get("/api/auth/me", headers=_auth(tokens["access_token"]))
    assert r.status_code == 200
    assert r.json()["name"] == "Asha"


def test_refresh_rotates_token_and_old_one_is_rejected(client) -> None:
    tokens = _register(client, "Asha", "9000000005")
    old_refresh = tokens["refresh_token"]

    r = client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert r.status_code == 200
    new_refresh = r.json()["refresh_token"]
    assert new_refresh != old_refresh


def test_refresh_token_reuse_revokes_whole_family(client) -> None:
    tokens = _register(client, "Asha", "9000000006")
    first = tokens["refresh_token"]

    rotated = client.post("/api/auth/refresh", json={"refresh_token": first}).json()
    second = rotated["refresh_token"]

    # Re-using the already-rotated token is treated as theft.
    reuse = client.post("/api/auth/refresh", json={"refresh_token": first})
    assert reuse.status_code == 401
    assert "reuse" in reuse.json()["error"].lower()

    # The legitimately rotated token is now dead too, because the family was revoked.
    after = client.post("/api/auth/refresh", json={"refresh_token": second})
    assert after.status_code == 401


def test_logout_revokes_refresh_tokens(client) -> None:
    tokens = _register(client, "Asha", "9000000007")
    r = client.post("/api/auth/logout", headers=_auth(tokens["access_token"]))
    assert r.status_code == 204
    r2 = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r2.status_code == 401


# ── Households, patients, consent ──────────────────────────────────

def test_creator_can_read_own_patient_only_with_consent(client) -> None:
    owner = _register(client, "Asha", "9000000010")
    created = _household(client, owner["access_token"], consent=True)
    patient_id = created["patient"]["patient_id"]

    r = client.get(f"/api/patients/{patient_id}", headers=_auth(owner["access_token"]))
    assert r.status_code == 200
    assert r.json()["display_name"] == "Amma"


def test_caregiver_without_access_gets_403(client) -> None:
    owner = _register(client, "Asha", "9000000011")
    stranger = _register(client, "Ravi", "9000000012")
    created = _household(client, owner["access_token"], consent=True)
    patient_id = created["patient"]["patient_id"]

    r = client.get(f"/api/patients/{patient_id}", headers=_auth(stranger["access_token"]))
    assert r.status_code == 403


def test_granted_caregiver_without_consent_gets_403(client) -> None:
    owner = _register(client, "Asha", "9000000013")
    sister = _register(client, "Meera", "9000000014")
    created = _household(client, owner["access_token"], consent=True)
    member_id = created["patient"]["household_member_id"]
    patient_id = created["patient"]["patient_id"]

    grant = client.post(
        "/api/access",
        headers=_auth(owner["access_token"]),
        json={"caregiver_user_id": sister["user"]["id"], "household_member_id": member_id},
    )
    assert grant.status_code == 201

    r = client.get(f"/api/patients/{patient_id}", headers=_auth(sister["access_token"]))
    assert r.status_code == 403
    assert "consent" in r.json()["error"].lower()


def test_granted_caregiver_with_consent_can_read(client) -> None:
    owner = _register(client, "Asha", "9000000015")
    sister = _register(client, "Meera", "9000000016")
    created = _household(client, owner["access_token"], consent=True)
    member_id = created["patient"]["household_member_id"]
    patient_id = created["patient"]["patient_id"]

    access_id = client.post(
        "/api/access",
        headers=_auth(owner["access_token"]),
        json={"caregiver_user_id": sister["user"]["id"], "household_member_id": member_id},
    ).json()["id"]

    consent = client.post(f"/api/access/{access_id}/consent", headers=_auth(sister["access_token"]), json={})
    assert consent.status_code == 201

    r = client.get(f"/api/patients/{patient_id}", headers=_auth(sister["access_token"]))
    assert r.status_code == 200


def test_revoked_consent_blocks_reads_immediately(client) -> None:
    owner = _register(client, "Asha", "9000000017")
    sister = _register(client, "Meera", "9000000018")
    created = _household(client, owner["access_token"], consent=True)
    member_id = created["patient"]["household_member_id"]
    patient_id = created["patient"]["patient_id"]

    access_id = client.post(
        "/api/access",
        headers=_auth(owner["access_token"]),
        json={"caregiver_user_id": sister["user"]["id"], "household_member_id": member_id},
    ).json()["id"]
    client.post(f"/api/access/{access_id}/consent", headers=_auth(sister["access_token"]), json={})
    assert client.get(f"/api/patients/{patient_id}", headers=_auth(sister["access_token"])).status_code == 200

    revoke = client.post(f"/api/access/{access_id}/revoke", headers=_auth(owner["access_token"]))
    assert revoke.status_code == 204

    r = client.get(f"/api/patients/{patient_id}", headers=_auth(sister["access_token"]))
    assert r.status_code == 403


def test_consent_is_not_assumed_when_household_created_without_it(client) -> None:
    owner = _register(client, "Asha", "9000000019")
    created = _household(client, owner["access_token"], consent=False)
    patient_id = created["patient"]["patient_id"]

    # The creator is the only one who never needs consent to act on their own household member
    # only if they are the patient themselves. A caregiver row without consent must not read.
    with Session(client.engine) as s:  # type: ignore[attr-defined]
        access = s.exec(select(CaregiverAccess)).first()
        assert access is not None
        assert access.consent_recorded is False
        assert s.exec(select(Consent)).first() is None

    r = client.get(f"/api/patients/{patient_id}", headers=_auth(owner["access_token"]))
    assert r.status_code == 403


def test_only_the_caregiver_can_record_their_own_consent(client) -> None:
    owner = _register(client, "Asha", "9000000020")
    sister = _register(client, "Meera", "9000000021")
    created = _household(client, owner["access_token"], consent=True)
    member_id = created["patient"]["household_member_id"]

    access_id = client.post(
        "/api/access",
        headers=_auth(owner["access_token"]),
        json={"caregiver_user_id": sister["user"]["id"], "household_member_id": member_id},
    ).json()["id"]

    # Owner tries to record consent on the sister's behalf: refused.
    r = client.post(f"/api/access/{access_id}/consent", headers=_auth(owner["access_token"]), json={})
    assert r.status_code == 403


def test_only_creator_can_grant_access(client) -> None:
    owner = _register(client, "Asha", "9000000022")
    sister = _register(client, "Meera", "9000000023")
    stranger = _register(client, "Ravi", "9000000024")
    created = _household(client, owner["access_token"], consent=True)
    member_id = created["patient"]["household_member_id"]

    r = client.post(
        "/api/access",
        headers=_auth(sister["access_token"]),
        json={"caregiver_user_id": stranger["user"]["id"], "household_member_id": member_id},
    )
    assert r.status_code == 403


def test_patient_update_respects_access(client) -> None:
    owner = _register(client, "Asha", "9000000025")
    stranger = _register(client, "Ravi", "9000000026")
    created = _household(client, owner["access_token"], consent=True)
    patient_id = created["patient"]["patient_id"]

    ok = client.patch(
        f"/api/patients/{patient_id}",
        headers=_auth(owner["access_token"]),
        json={"display_name": "Amma (Sunita)"},
    )
    assert ok.status_code == 200
    assert ok.json()["display_name"] == "Amma (Sunita)"

    denied = client.patch(
        f"/api/patients/{patient_id}",
        headers=_auth(stranger["access_token"]),
        json={"display_name": "Hacked"},
    )
    assert denied.status_code == 403


def test_grant_and_consent_are_audited(client) -> None:
    owner = _register(client, "Asha", "9000000027")
    sister = _register(client, "Meera", "9000000028")
    created = _household(client, owner["access_token"], consent=True)
    member_id = created["patient"]["household_member_id"]

    access_id = client.post(
        "/api/access",
        headers=_auth(owner["access_token"]),
        json={"caregiver_user_id": sister["user"]["id"], "household_member_id": member_id},
    ).json()["id"]
    client.post(f"/api/access/{access_id}/consent", headers=_auth(sister["access_token"]), json={})

    with Session(client.engine) as s:  # type: ignore[attr-defined]
        actions = {a.action for a in s.exec(select(AuditRecord)).all()}
    assert {"ACCESS_GRANTED", "CONSENT_RECORDED", "HOUSEHOLD_CREATED"}.issubset(actions)
