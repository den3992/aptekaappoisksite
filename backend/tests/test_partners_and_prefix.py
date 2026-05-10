"""
Tests for:
- GET /api/search prefix filter (Cyrillic letters)
- POST /api/partner-requests (validation + happy path)
- Admin endpoints: list / approve / reject (and bad token)
- Regression: existing endpoints still work
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://determined-rubin-2.preview.emergentagent.com").rstrip("/")
# Backend reads ADMIN_TOKEN from /app/backend/.env on startup. Fallback in code
# is 'dev-admin-token-change-me' but env overrides it in this preview environment.
def _read_admin_token_from_env_file() -> str:
    try:
        with open("/app/backend/.env", "r") as f:
            for line in f:
                if line.startswith("ADMIN_TOKEN="):
                    return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return "dev-admin-token-change-me"

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN") or _read_admin_token_from_env_file()


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


# -------- Prefix filter --------

@pytest.mark.parametrize("letter", ["А", "Б", "Я"])
def test_search_prefix_returns_only_matching(s, letter):
    r = s.get(f"{BASE_URL}/api/search", params={"prefix": letter, "page_size": 10})
    assert r.status_code == 200, r.text
    data = r.json()
    assert "total" in data and "items" in data
    if data["total"] == 0:
        # 'Я' may legitimately be empty; only 'А' must have matches.
        if letter == "А":
            pytest.fail("Expected meds starting with 'А' but total=0")
        return
    for it in data["items"]:
        assert it["name"][:1].upper() == letter.upper(), f"{it['name']} doesn't start with {letter}"


def test_search_prefix_case_insensitive(s):
    r1 = s.get(f"{BASE_URL}/api/search", params={"prefix": "А", "page_size": 5})
    r2 = s.get(f"{BASE_URL}/api/search", params={"prefix": "а", "page_size": 5})
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["total"] == r2.json()["total"]


def test_search_no_prefix_still_works(s):
    r = s.get(f"{BASE_URL}/api/search", params={"page_size": 5})
    assert r.status_code == 200
    assert r.json()["total"] > 0


# -------- Partner requests --------

@pytest.fixture(scope="module")
def created_request(s):
    payload = {
        "chain": "TEST_AptekaChain",
        "city": "Москва",
        "email": "TEST_partner@example.com",
        "phone": "+7 (999) 000-11-22",
        "count": "5-20",
        "comment": "Тестовая заявка",
    }
    r = s.post(f"{BASE_URL}/api/partner-requests", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "id" in data
    assert data["status"] == "new"
    assert "created_at" in data
    return data


def test_create_partner_request(created_request):
    assert created_request["id"].startswith("pr-")


def test_create_partner_request_invalid_email(s):
    r = s.post(f"{BASE_URL}/api/partner-requests", json={
        "chain": "TEST_X", "email": "not-an-email"
    })
    assert r.status_code == 422


def test_create_partner_request_missing_email(s):
    r = s.post(f"{BASE_URL}/api/partner-requests", json={"chain": "TEST_X"})
    assert r.status_code == 422


def test_create_partner_request_missing_chain(s):
    r = s.post(f"{BASE_URL}/api/partner-requests", json={"email": "a@b.com"})
    assert r.status_code == 422


# -------- Admin endpoints --------

def test_admin_list_bad_token(s):
    r = s.get(f"{BASE_URL}/api/admin/partner-requests/wrong-token")
    assert r.status_code == 403


def test_admin_list_includes_created(s, created_request):
    r = s.get(f"{BASE_URL}/api/admin/partner-requests/{ADMIN_TOKEN}")
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)
    ids = [it["id"] for it in items]
    assert created_request["id"] in ids


def test_admin_approve_bad_token(s, created_request):
    r = s.post(f"{BASE_URL}/api/admin/partner-requests/wrong/{created_request['id']}/approve")
    assert r.status_code == 403


def test_admin_approve_then_reject_flow(s):
    # Create separate requests for approve and reject
    r_approve = s.post(f"{BASE_URL}/api/partner-requests", json={
        "chain": "TEST_ToApprove", "email": "TEST_approve@example.com"
    }).json()
    r_reject = s.post(f"{BASE_URL}/api/partner-requests", json={
        "chain": "TEST_ToReject", "email": "TEST_reject@example.com"
    }).json()

    # Approve
    rA = s.post(f"{BASE_URL}/api/admin/partner-requests/{ADMIN_TOKEN}/{r_approve['id']}/approve")
    assert rA.status_code == 200, rA.text
    bodyA = rA.json()
    assert bodyA["ok"] is True
    assert bodyA["status"] in ("approved", "already-approved")
    assert bodyA["token"] and isinstance(bodyA["token"], str)
    assert bodyA["pharmacy_id"].startswith("partner-")

    # Idempotent re-approve
    rA2 = s.post(f"{BASE_URL}/api/admin/partner-requests/{ADMIN_TOKEN}/{r_approve['id']}/approve")
    assert rA2.status_code == 200
    assert rA2.json()["token"] == bodyA["token"]

    # Reject the other
    rR = s.post(f"{BASE_URL}/api/admin/partner-requests/{ADMIN_TOKEN}/{r_reject['id']}/reject")
    assert rR.status_code == 200
    assert rR.json()["status"] == "rejected"

    # Verify in admin list
    items = s.get(f"{BASE_URL}/api/admin/partner-requests/{ADMIN_TOKEN}").json()
    by_id = {it["id"]: it for it in items}
    assert by_id[r_approve["id"]]["status"] == "approved"
    assert by_id[r_reject["id"]]["status"] == "rejected"


def test_admin_reject_unknown_id(s):
    r = s.post(f"{BASE_URL}/api/admin/partner-requests/{ADMIN_TOKEN}/pr-nonexistent/reject")
    assert r.status_code == 404


# -------- Regression --------

def test_regression_categories(s):
    r = s.get(f"{BASE_URL}/api/categories")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list) and len(data) >= 8
    assert all("slug" in c and "title" in c for c in data)


def test_regression_pharmacies(s):
    r = s.get(f"{BASE_URL}/api/pharmacies", params={"city": "msk"})
    assert r.status_code == 200
    assert isinstance(r.json(), list) and len(r.json()) > 0


def test_regression_medication_detail(s):
    r = s.get(f"{BASE_URL}/api/medications/determined-rubin-2")
    # may be 404 if slug not seeded, but endpoint should not 500
    assert r.status_code in (200, 404)


def test_regression_search_basic(s):
    r = s.get(f"{BASE_URL}/api/search", params={"q": "нурофен"})
    assert r.status_code == 200
    assert r.json()["total"] >= 0
