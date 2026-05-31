"""Tests for АптекаА catalog migration: cities, categories, search, medications,
pharmacies, SEO endpoints (robots/sitemap/render), and voice smoke tests."""
import os
import re
import pytest
import requests
from urllib.parse import quote

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://determined-rubin-2.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"

NUROFEN_SLUG = "nurofen-200-mg-tabletki-pokrytye-obolochkoy"
PARACETAMOL_SLUG = "paracetamol-500-mg-tabletki-pokrytye-obolochkoy"


@pytest.fixture(scope="module")
def s():
    return requests.Session()


# ---------- Cities & categories ----------
class TestCitiesCategories:
    def test_cities(self, s):
        r = s.get(f"{API}/cities", timeout=15)
        assert r.status_code == 200
        data = r.json()
        slugs = {c["slug"] for c in data}
        assert {"msk", "spb"}.issubset(slugs)
        assert len(data) == 2

    def test_categories(self, s):
        r = s.get(f"{API}/categories", timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) == 11
        # Each must have slug, title, count
        for c in data:
            assert "slug" in c and "title" in c and "count" in c
        total = sum(c["count"] for c in data)
        # Should be > 0 (real DB has 23303 meds)
        assert total > 0, f"All category counts are 0: {data}"


# ---------- Search ----------
class TestSearch:
    def test_search_nurofen(self, s):
        r = s.get(f"{API}/search", params={"q": "нурофен"}, timeout=20)
        assert r.status_code == 200
        data = r.json()
        assert "total" in data and "items" in data
        assert data["total"] >= 1
        assert len(data["items"]) >= 1
        item = data["items"][0]
        for k in ("slug", "name", "rx", "vital", "variants_count"):
            assert k in item, f"missing key {k} in {item}"

    def test_search_paracetamol_pagination(self, s):
        r1 = s.get(f"{API}/search", params={"q": "парацетамол", "page": 1, "page_size": 24}, timeout=20)
        assert r1.status_code == 200
        d1 = r1.json()
        assert d1["page"] == 1
        assert len(d1["items"]) <= 24
        if d1["total"] > 24:
            r2 = s.get(f"{API}/search", params={"q": "парацетамол", "page": 2, "page_size": 24}, timeout=20)
            assert r2.status_code == 200
            d2 = r2.json()
            assert d2["page"] == 2
            slugs1 = {x["slug"] for x in d1["items"]}
            slugs2 = {x["slug"] for x in d2["items"]}
            assert slugs1.isdisjoint(slugs2), "Page 1 and page 2 overlap"

    def test_search_filter_category(self, s):
        r = s.get(f"{API}/search", params={"category": "ot-prostudy", "page_size": 10}, timeout=20)
        assert r.status_code == 200
        data = r.json()
        for item in data["items"]:
            assert item["category"] == "ot-prostudy"

    def test_search_filter_rx_false(self, s):
        r = s.get(f"{API}/search", params={"rx": "false", "page_size": 10}, timeout=20)
        assert r.status_code == 200
        data = r.json()
        for item in data["items"]:
            assert item["rx"] is False

    def test_search_suggest(self, s):
        r = s.get(f"{API}/search/suggest", params={"q": "нур"}, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        # At least some suggestion should start with нур (case-insensitive) in name or mnn
        # Tolerate empty if DB lacks the prefix; but we expect it for nurofen
        assert len(data) >= 1, f"No suggestions for 'нур': {data}"


# ---------- Medication detail ----------
class TestMedDetail:
    def test_med_detail_nurofen(self, s):
        r = s.get(f"{API}/medications/{NUROFEN_SLUG}", timeout=15)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["slug"] == NUROFEN_SLUG
        assert "variants" in d and isinstance(d["variants"], list)
        assert "prices_by_city" in d
        assert "msk" in d["prices_by_city"] and "spb" in d["prices_by_city"]
        assert isinstance(d["prices_by_city"]["msk"], list)
        assert len(d["prices_by_city"]["msk"]) >= 1
        for row in d["prices_by_city"]["msk"]:
            assert "pharmacy_id" in row and "price" in row and "qty" in row

    def test_med_analogs(self, s):
        r = s.get(f"{API}/medications/{NUROFEN_SLUG}/analogs", timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) <= 8
        # Should not include itself
        for a in data:
            assert a["slug"] != NUROFEN_SLUG

    def test_med_detail_404(self, s):
        r = s.get(f"{API}/medications/no-such-slug-xyz", timeout=15)
        assert r.status_code == 404


# ---------- Pharmacies ----------
class TestPharmacies:
    def test_pharmacies_msk(self, s):
        r = s.get(f"{API}/pharmacies", params={"city": "msk"}, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 12, f"Expected 12 msk pharmacies, got {len(data)}"
        for p in data:
            assert p["city"] == "msk"

    def test_pharmacies_spb(self, s):
        r = s.get(f"{API}/pharmacies", params={"city": "spb"}, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 8, f"Expected 8 spb pharmacies, got {len(data)}"
        for p in data:
            assert p["city"] == "spb"

    def test_pharmacy_detail(self, s):
        r = s.get(f"{API}/pharmacies/p1", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d["id"] == "p1"
        for k in ("name", "address", "lat", "lng"):
            assert k in d


# ---------- SEO ----------
class TestSEO:
    def test_robots(self, s):
        r = s.get(f"{API}/seo/robots.txt", timeout=15)
        assert r.status_code == 200
        body = r.text
        assert "Sitemap:" in body
        assert "Host:" in body
        assert "User-agent: Yandex" in body

    def test_sitemap_index(self, s):
        r = s.get(f"{API}/seo/sitemap.xml", timeout=15)
        assert r.status_code == 200
        assert "<sitemapindex" in r.text
        assert "sitemap_meds_1.xml" in r.text

    def test_sitemap_meds_1(self, s):
        r = s.get(f"{API}/seo/sitemap_meds_1.xml", timeout=30)
        assert r.status_code == 200
        assert "<urlset" in r.text
        assert "/msk/preparaty/" in r.text

    def test_seo_render_home(self, s):
        r = s.get(f"{API}/seo/render", params={"path": "/msk"}, timeout=20)
        assert r.status_code == 200
        h = r.text
        assert "<title>" in h
        assert "<h1>" in h
        assert "schema.org" in h
        assert "/msk/kategorii/" in h or "kategorii" in h
        assert "/msk/apteki/" in h

    def test_seo_render_med(self, s):
        r = s.get(f"{API}/seo/render", params={"path": f"/msk/preparaty/{NUROFEN_SLUG}"}, timeout=20)
        assert r.status_code == 200
        h = r.text
        assert "<title>" in h
        assert '"@type": "Drug"' in h or '"@type":"Drug"' in h

    def test_seo_render_pharmacy(self, s):
        r = s.get(f"{API}/seo/render", params={"path": "/msk/apteki/p1"}, timeout=20)
        assert r.status_code == 200
        h = r.text
        assert '"@type": "Pharmacy"' in h or '"@type":"Pharmacy"' in h
        assert "<h1>" in h


# ---------- Voice smoke ----------
class TestVoiceSmoke:
    def test_voice_tts_smoke(self, s):
        r = s.post(f"{API}/voice/tts", json={"text": "Тест"}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        # Either ogg or mpeg
        assert r.headers.get("content-type", "").startswith("audio/")
        assert len(r.content) > 100
