"""Iteration 2 tests: marketplaces rename, prices, cost template, legacy cost parser,
Amazon PO ASIN fix, renormalize-marketplaces."""
import io
import os
import requests
import pytest

from conftest import BASE_URL

SAMPLE_DIR = "/app/sample_data"


# --------- Marketplaces rename ---------
class TestMarketplacesRename:
    def test_marketplaces_includes_mano_mano_not_mon_echelle(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/marketplaces", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert "Mano Mano" in data, f"Expected 'Mano Mano' in marketplaces, got {data}"
        assert "Mon Echelle" not in data, f"'Mon Echelle' should NOT appear; got {data}"
        assert "MONECHELLE" not in data


# --------- Renormalize ---------
class TestRenormalize:
    def test_renormalize_marketplaces(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/admin/renormalize-marketplaces", headers=auth_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "updated" in d
        assert isinstance(d["updated"], int)


# --------- /api/skus/prices ---------
class TestSkuPrices:
    def test_prices_basic(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/skus/prices", headers=auth_headers, params={"limit": 10})
        assert r.status_code == 200, r.text
        d = r.json()
        assert "marketplaces" in d
        assert "items" in d
        assert isinstance(d["marketplaces"], list)
        assert isinstance(d["items"], list)
        if d["items"]:
            it = d["items"][0]
            for k in ("sku", "product_name", "prices", "total_units"):
                assert k in it, f"missing key {k} in item"
            assert isinstance(it["prices"], dict)
            if it["prices"]:
                mk, p = next(iter(it["prices"].items()))
                for k in ("avg", "min", "max", "units", "orders", "currency", "last_order"):
                    assert k in p, f"missing field {k} in price object for {mk}"

    def test_prices_filter_by_sku(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/skus/prices", headers=auth_headers, params={"sku": "privacy", "limit": 50})
        assert r.status_code == 200
        items = r.json()["items"]
        for it in items:
            assert "privacy" in it["sku"].lower(), f"SKU {it['sku']} does not contain 'privacy'"

    def test_prices_export_csv(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/skus/prices/export", headers=auth_headers)
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")
        text = r.text
        lines = text.splitlines()
        assert len(lines) >= 1
        header = lines[0]
        assert header.startswith("SKU,Product"), f"Unexpected header: {header}"
        # Must contain at least one '(avg)' and '(units)' column if there is data
        assert "(avg)" in header
        assert "(units)" in header


# --------- /api/templates/cost ---------
class TestCostTemplate:
    def test_cost_template_csv(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/templates/cost", headers=auth_headers, timeout=60)
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")
        text = r.text
        lines = text.splitlines()
        assert lines[0] == "sku,product_name,cost_per_unit,shipping_cost,currency", f"Unexpected header: {lines[0]}"
        # Should have rows
        assert len(lines) > 1, "Cost template has no SKU rows"


# --------- Cost upload: legacy Sheet3 workbook ---------
class TestLegacyCostUpload:
    def test_upload_cost_prod_xlsx(self, auth_headers):
        path = os.path.join(SAMPLE_DIR, "cost_prod.xlsx")
        if not os.path.exists(path):
            pytest.skip("cost_prod.xlsx not present")
        with open(path, "rb") as f:
            r = requests.post(
                f"{BASE_URL}/api/uploads/costs",
                headers=auth_headers,
                files={"file": ("cost_prod.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                timeout=180,
            )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["rows_total"] > 0, f"Expected rows_total > 0, got {d}"
        assert (d.get("inserted", 0) + d.get("updated", 0)) > 0, f"Expected inserts+updates > 0, got {d}"

    def test_upload_simple_csv_still_works(self, auth_headers):
        csv_content = "sku,product_name,cost_per_unit,shipping_cost,currency\nTEST_ITER2_001,Foo,1.10,0.20,EUR\nTEST_ITER2_002,Bar,2.50,0.30,EUR\n"
        r = requests.post(
            f"{BASE_URL}/api/uploads/costs",
            headers=auth_headers,
            files={"file": ("costs.csv", io.BytesIO(csv_content.encode()), "text/csv")},
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["rows_total"] == 2
        # cleanup
        for sku in ("TEST_ITER2_001", "TEST_ITER2_002"):
            requests.delete(f"{BASE_URL}/api/costs/{sku}", headers=auth_headers)


# --------- Amazon PO ASIN bug fix ---------
class TestAmazonPoAsinFix:
    def test_no_nan_skus_in_orders(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/orders", headers=auth_headers, params={"sku": "nan", "limit": 5})
        assert r.status_code == 200
        d = r.json()
        # SKU filter is substring (case-insensitive) — so this could include any sku containing 'nan'.
        # Stricter: ensure no order has sku exactly equal to 'nan' (case-insensitive).
        bad = [it for it in d.get("items", []) if (it.get("sku") or "").strip().lower() == "nan"]
        assert len(bad) == 0, f"Found {len(bad)} orders with sku=='nan' (Amazon PO ASIN fallback bug)"

    def test_top_skus_has_amazon_asin(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/dashboard/top-skus", headers=auth_headers, params={"limit": 20})
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)
        # No 'nan' SKU should be a top performer
        nan_rows = [x for x in rows if (x.get("sku") or "").strip().lower() == "nan"]
        assert not nan_rows, f"top-skus contains 'nan' sku: {nan_rows}"


# --------- Margin / summary sanity ---------
class TestSummaryMargin:
    def test_summary_has_cogs_and_margin(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/dashboard/summary", headers=auth_headers)
        assert r.status_code == 200
        d = r.json()
        assert d["revenue_eur"] > 0
        assert d["cogs_eur"] >= 0
        assert -100 <= d["margin_pct"] <= 100
