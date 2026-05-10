"""
Tests for new features in iteration 4:
  - LLM-enriched medications (`enrichment` field on /api/medications/{slug})
  - SEO render emits enrichment HTML block + uses summary as meta description
  - Regression on /api/admin/partner-requests/{TOKEN} endpoints
"""
import os
import re
import pathlib
import requests
import pytest

# Resolve BASE_URL from frontend/.env (preview URL the user actually hits)
_FE_ENV = pathlib.Path("/app/frontend/.env").read_text()
BASE_URL = re.search(r"REACT_APP_BACKEND_URL=(.+)", _FE_ENV).group(1).strip().rstrip("/")

# Resolve ADMIN_TOKEN from backend/.env
_BE_ENV = pathlib.Path("/app/backend/.env").read_text()
ADMIN_TOKEN = re.search(r"ADMIN_TOKEN=(.+)", _BE_ENV).group(1).strip()

ENRICHED_SLUG = "paracetamol-10-mg-ml-rastvor-dlya-infuziy"
NON_ENRICHED_SLUG = "5-nok-50-mg-tabletki-pokrytye-obolochkoy"


# ---------- Enrichment field on medication API ---------------------------- #

class TestMedicationEnrichmentField:
    def test_enriched_med_has_full_enrichment_object(self):
        r = requests.get(f"{BASE_URL}/api/medications/{ENRICHED_SLUG}")
        assert r.status_code == 200
        data = r.json()
        assert "enrichment" in data, "enrichment key missing"
        e = data["enrichment"]
        assert e is not None, "enrichment should be present for enriched med"
        # required keys
        for k in ["summary", "indications", "contraindications", "how_to_take",
                  "disclaimer", "generated_at", "model"]:
            assert k in e, f"missing {k} in enrichment"
        # types & non-empty
        assert isinstance(e["summary"], str) and len(e["summary"]) > 20
        assert isinstance(e["indications"], list) and len(e["indications"]) > 0
        assert isinstance(e["contraindications"], list) and len(e["contraindications"]) > 0
        assert isinstance(e["how_to_take"], str) and len(e["how_to_take"]) > 5
        assert isinstance(e["disclaimer"], str)

    def test_non_enriched_med_has_no_enrichment_block(self):
        r = requests.get(f"{BASE_URL}/api/medications/{NON_ENRICHED_SLUG}")
        assert r.status_code == 200
        data = r.json()
        # graceful absence: either missing key or null
        assert data.get("enrichment") in (None, {}), \
            f"expected no enrichment on {NON_ENRICHED_SLUG}, got {data.get('enrichment')}"


# ---------- SEO render endpoint ------------------------------------------- #

class TestSEORenderEnrichment:
    def test_seo_render_for_enriched_med_contains_html_blocks(self):
        url = f"{BASE_URL}/api/seo/render"
        r = requests.get(url, params={"path": f"/msk/preparaty/{ENRICHED_SLUG}"})
        assert r.status_code == 200
        html = r.text
        assert "<h2>О препарате</h2>" in html
        assert "<h3>Показания</h3>" in html
        assert "<h3>Противопоказания</h3>" in html
        assert "<h3>Способ применения</h3>" in html
        # meta description should be the LLM summary (sanity: long-ish, no fallback "Сравните цены...")
        m = re.search(r'<meta name="description" content="([^"]+)"', html)
        assert m, "meta description missing"
        desc = m.group(1)
        # summary may itself end with the city tagline; check it's substantive (>60 chars)
        assert len(desc) > 60, f"meta description seems short / fallback only: {desc!r}"

    def test_seo_render_for_non_enriched_med_omits_enrichment_block(self):
        url = f"{BASE_URL}/api/seo/render"
        r = requests.get(url, params={"path": f"/msk/preparaty/{NON_ENRICHED_SLUG}"})
        assert r.status_code == 200
        html = r.text
        assert "<h2>О препарате</h2>" not in html, \
            "enrichment block should NOT render for non-enriched med"


# ---------- Admin partner-requests regression ----------------------------- #

class TestAdminPartnerRequestsRegression:
    def test_admin_list_with_valid_token(self):
        r = requests.get(f"{BASE_URL}/api/admin/partner-requests/{ADMIN_TOKEN}")
        assert r.status_code == 200
        items = r.json()
        assert isinstance(items, list)

    def test_admin_list_with_bad_token_403(self):
        r = requests.get(f"{BASE_URL}/api/admin/partner-requests/WRONG-TOKEN-xyz")
        assert r.status_code == 403

    def test_admin_status_filter_new(self):
        r = requests.get(f"{BASE_URL}/api/admin/partner-requests/{ADMIN_TOKEN}",
                         params={"status": "new"})
        assert r.status_code == 200
        for it in r.json():
            assert it["status"] == "new"

    def test_admin_approve_then_reject_flow(self):
        # create a fresh request
        payload = {
            "chain": "TEST_Iter4_Admin",
            "email": "iter4admin@example.com",
            "phone": "+79990000000",
            "city": "Москва",
            "count": "5",
            "comment": "iteration 4 admin flow",
        }
        cr = requests.post(f"{BASE_URL}/api/partner-requests", json=payload)
        assert cr.status_code in (200, 201)
        rid = cr.json().get("id") or cr.json().get("_id") or cr.json().get("request_id")
        # fall back: find via listing
        if not rid:
            lst = requests.get(f"{BASE_URL}/api/admin/partner-requests/{ADMIN_TOKEN}",
                               params={"status": "new"}).json()
            cand = [x for x in lst if x.get("chain") == payload["chain"]]
            assert cand, "couldn't locate created request"
            rid = cand[0]["id"]
        # approve
        ar = requests.post(f"{BASE_URL}/api/admin/partner-requests/{ADMIN_TOKEN}/{rid}/approve")
        assert ar.status_code == 200
        approve_data = ar.json()
        assert "token" in approve_data
        assert isinstance(approve_data["token"], str) and len(approve_data["token"]) > 10
        # verify it now appears in approved list
        appr_lst = requests.get(f"{BASE_URL}/api/admin/partner-requests/{ADMIN_TOKEN}",
                                params={"status": "approved"}).json()
        assert any(x["id"] == rid for x in appr_lst), "approved row missing from approved list"

    def test_admin_reject_a_new_request(self):
        payload = {
            "chain": "TEST_Iter4_Reject",
            "email": "iter4reject@example.com",
            "phone": "+79990000001",
            "city": "Москва",
            "count": "2",
            "comment": "iter4 reject",
        }
        cr = requests.post(f"{BASE_URL}/api/partner-requests", json=payload)
        assert cr.status_code in (200, 201)
        rid = cr.json().get("id")
        if not rid:
            lst = requests.get(f"{BASE_URL}/api/admin/partner-requests/{ADMIN_TOKEN}",
                               params={"status": "new"}).json()
            rid = next(x["id"] for x in lst if x["chain"] == payload["chain"])
        rr = requests.post(f"{BASE_URL}/api/admin/partner-requests/{ADMIN_TOKEN}/{rid}/reject")
        assert rr.status_code == 200
        rej = requests.get(f"{BASE_URL}/api/admin/partner-requests/{ADMIN_TOKEN}",
                           params={"status": "rejected"}).json()
        assert any(x["id"] == rid for x in rej)
