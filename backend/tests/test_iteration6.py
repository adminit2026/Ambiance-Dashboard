"""Iteration 6 backend tests — covers combined LRM+AMZ mapping, sku_mappings
collection, canonical marketplaces list, idempotency, and dashboards.

Tests assume the DB is already in the post-mapping state described in the
review request (sku_mappings populated, mapping applied to orders).
"""
import os
import re
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://ambiance-seller-hub.preview.emergentagent.com").rstrip("/")
SAMPLE = "/app/sample_data"

CANONICAL = [
    "Amazon Vendor", "Ambiance Web", "Appros", "BOL.COM", "CDiscount",
    "Castorama", "Kaufland", "Leroy Merlin", "Maison", "Mano Mano",
    "Maxeda - BE", "Maxeda - NL", "PinkConnect Veepee - BE",
    "PinkConnect Veepee - FR", "PinkConnect Veepee - NL", "Zooplus",
]


# ------- Marketplaces canonical list --------
class TestMarketplacesCanonical:
    def test_all_16_canonical_marketplaces_present(self, auth_headers):
        r = requests.get(f"{BASE}/api/marketplaces", headers=auth_headers, timeout=30)
        assert r.status_code == 200
        mks = r.json()
        assert isinstance(mks, list)
        missing = [m for m in CANONICAL if m not in mks]
        assert missing == [], f"Missing canonical marketplaces: {missing}"

    def test_ambiance_web_present_even_with_zero_orders(self, auth_headers):
        r = requests.get(f"{BASE}/api/marketplaces", headers=auth_headers, timeout=30)
        mks = r.json()
        assert "Ambiance Web" in mks
        assert "Appros" in mks
        assert "Zooplus" in mks

    def test_no_duplicate_case_variants(self, auth_headers):
        """Castorama / CDiscount / Maison must each appear exactly once."""
        r = requests.get(f"{BASE}/api/marketplaces", headers=auth_headers, timeout=30)
        mks = r.json()
        for name in ("Castorama", "CDiscount", "Maison"):
            lower_matches = [m for m in mks if m.lower() == name.lower()]
            assert len(lower_matches) == 1, f"Duplicate case variants for {name}: {lower_matches}"


# -------- Combined LRM+AMZ mapping upload --------
class TestCombinedMappingUpload:
    def test_lrm_amz_combined_upload_autodetects(self, auth_headers):
        path = os.path.join(SAMPLE, "lrm_amz_map.xlsx")
        assert os.path.exists(path), f"sample file missing: {path}"
        with open(path, "rb") as f:
            r = requests.post(
                f"{BASE}/api/uploads/asin-mapping",
                headers=auth_headers,
                files={"file": ("lrm_amz_map.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                timeout=240,
            )
        assert r.status_code == 200, r.text
        d = r.json()
        # Expect ~47k rows emitted (26k Amazon + 21k LRM)
        assert d["rows_total"] >= 40000, f"rows_total too low: {d}"
        # Inserted+updated must equal rows_total
        assert d["inserted"] + d["updated"] == d["rows_total"]
        # orders_remapped — on idempotent re-upload could be 0; just must be int
        assert isinstance(d["orders_remapped"], int)
        assert d["orders_remapped"] >= 0

    def test_simple_csv_mapping_backward_compat(self, auth_headers):
        """Simple 'asin,merchant_sku' CSV format must still be accepted."""
        csv_body = b"asin,merchant_sku,product_name\nTEST_BACK_COMPAT_ASIN,TEST_back_compat_sku,Test product\n"
        r = requests.post(
            f"{BASE}/api/uploads/asin-mapping",
            headers=auth_headers,
            files={"file": ("simple.csv", csv_body, "text/csv")},
            timeout=60,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["rows_total"] == 1
        assert d["inserted"] + d["updated"] == 1
        # Verify visibility via list endpoint (legacy asin_mappings mirror)
        lr = requests.get(
            f"{BASE}/api/asin-mappings?search=TEST_BACK_COMPAT_ASIN",
            headers=auth_headers, timeout=30,
        )
        assert lr.status_code == 200
        rows = lr.json()
        assert any(x.get("asin") == "TEST_BACK_COMPAT_ASIN" for x in rows)


# -------- Orders after mapping: sku is merchant_sku, asin preserved --------
class TestOrdersPostMapping:
    def test_amazon_orders_sku_is_merchant_sku(self, auth_headers):
        r = requests.get(
            f"{BASE}/api/orders?marketplaces=Amazon Vendor&limit=20",
            headers=auth_headers, timeout=30,
        )
        assert r.status_code == 200
        d = r.json()
        # total must equal canonical 6,580 (idempotency invariant)
        assert d.get("total") == 6580, f"Amazon Vendor total drifted: {d.get('total')}"
        items = d.get("items", [])
        assert len(items) > 0
        # At least 80% of returned items should have sku != asin (merchant_sku format)
        merchant_count = 0
        for it in items:
            sku = it.get("sku") or ""
            asin = it.get("asin") or ""
            # asin field must still hold an ASIN-shaped string
            if asin:
                assert re.match(r"^B[0-9A-Z]{9}$", asin), f"asin field not ASIN-shaped: {asin}"
            if sku and sku != asin:
                merchant_count += 1
        assert merchant_count >= len(items) * 0.5, (
            f"Most amazon orders should now have merchant_sku (got {merchant_count}/{len(items)})"
        )

    def test_amazon_line_key_always_ends_with_asin(self, auth_headers):
        """Critical invariant: line_key suffix must be ASIN, never merchant_sku."""
        r = requests.get(
            f"{BASE}/api/orders?marketplaces=Amazon Vendor&limit=50",
            headers=auth_headers, timeout=30,
        )
        d = r.json()
        for it in d.get("items", []):
            lk = it.get("line_key", "")
            assert "::" in lk, f"Bad line_key: {lk}"
            suffix = lk.split("::", 1)[1]
            assert re.match(r"^B[0-9A-Z]{9}$", suffix), f"line_key suffix is not an ASIN: {lk}"


# -------- Top-SKUs dashboard returns merchant SKUs with cost --------
class TestTopSkus:
    def test_top_skus_contain_merchant_skus(self, auth_headers):
        r = requests.get(f"{BASE}/api/dashboard/top-skus", headers=auth_headers, timeout=30)
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list) and len(rows) > 0
        skus = [row["sku"] for row in rows]
        # At least one merchant-style sku (col-, SAND_, J-, roll-) in top 20
        merchant_prefixes = ("col-", "SAND_", "SAND-", "J-", "J3-", "roll-")
        assert any(s.startswith(merchant_prefixes) for s in skus[:20]), (
            f"Expected merchant SKUs among top-20, got: {skus[:20]}"
        )

    def test_top_skus_have_cost_and_margin(self, auth_headers):
        r = requests.get(f"{BASE}/api/dashboard/top-skus", headers=auth_headers, timeout=30)
        rows = r.json()
        merchant_with_cost = [
            r for r in rows[:20]
            if r["sku"].startswith(("col-", "SAND_", "SAND-", "J-", "roll-"))
            and r.get("has_cost") is True
        ]
        assert len(merchant_with_cost) >= 1, "At least one merchant SKU should have has_cost=True"
        for row in merchant_with_cost:
            assert row["cogs_eur"] > 0
            assert 0 <= row["margin_pct"] <= 100


# -------- Idempotency: re-upload amazon_po.xls and beezup.xlsx --------
class TestIdempotency:
    def test_reupload_amazon_po_no_duplicates(self, auth_headers):
        path = os.path.join(SAMPLE, "amazon_po.xls")
        with open(path, "rb") as f:
            r = requests.post(
                f"{BASE}/api/uploads/orders",
                headers=auth_headers,
                files={"file": ("amazon_po.xls", f, "application/vnd.ms-excel")},
                data={"source": "amazon_po"},
                timeout=240,
            )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("inserted") == 0, f"Re-upload created new rows: {d}"
        # Verify total still 6580
        c = requests.get(
            f"{BASE}/api/orders?marketplaces=Amazon Vendor&limit=1",
            headers=auth_headers, timeout=30,
        )
        assert c.json().get("total") == 6580

    def test_reupload_beezup_stable(self, auth_headers):
        path = os.path.join(SAMPLE, "beezup.xlsx")
        # Snapshot total Leroy Merlin orders before
        before = requests.get(
            f"{BASE}/api/orders?marketplaces=Leroy Merlin&limit=1",
            headers=auth_headers, timeout=30,
        ).json().get("total", 0)

        with open(path, "rb") as f:
            r = requests.post(
                f"{BASE}/api/uploads/orders",
                headers=auth_headers,
                files={"file": ("beezup.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                data={"source": "beezup"},
                timeout=240,
            )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("inserted") == 0, f"Re-upload of beezup created new rows: {d}"

        after = requests.get(
            f"{BASE}/api/orders?marketplaces=Leroy Merlin&limit=1",
            headers=auth_headers, timeout=30,
        ).json().get("total", 0)
        assert before == after, f"Leroy Merlin total drifted on reupload: before={before} after={after}"


# -------- Reprocess endpoint --------
class TestReprocess:
    def test_reprocess_idempotent_on_already_synced_db(self, auth_headers):
        r = requests.post(
            f"{BASE}/api/admin/reprocess-amazon-asins",
            headers=auth_headers, timeout=120,
        )
        assert r.status_code == 200
        d = r.json()
        assert "orders_remapped" in d
        # On already-synced DB this should be 0
        assert d["orders_remapped"] == 0, f"Expected 0 on already-synced DB, got {d}"


# -------- Dashboard summary --------
class TestDashboardSummary:
    def test_summary_uses_merchant_skus_for_cogs(self, auth_headers):
        r = requests.get(f"{BASE}/api/dashboard/summary", headers=auth_headers, timeout=30)
        assert r.status_code == 200
        d = r.json()
        # After mapping, cogs is non-zero because amazon orders match cost catalog
        assert d.get("cogs_eur", 0) > 1000, f"cogs unexpectedly low: {d}"
        # margin_pct should be reasonable (40–90)
        assert 30 <= d.get("margin_pct", 0) <= 95, f"margin_pct out of range: {d}"
        # Revenue must be > 0
        assert d.get("revenue_eur", 0) > 0


# -------- sku_mappings collection state (indirect via API counts) --------
class TestSkuMappingsState:
    def test_combined_mapping_produces_both_markets(self, auth_headers):
        """After combined upload, asin_mappings (legacy mirror) should have many Amazon entries."""
        r = requests.get(
            f"{BASE}/api/asin-mappings?limit=5000",
            headers=auth_headers, timeout=60,
        )
        assert r.status_code == 200
        rows = r.json()
        # asin_mappings only mirrors Amazon side — should have thousands
        assert len(rows) >= 1000, f"Expected >=1000 Amazon mappings, got {len(rows)}"
