"""Iteration 4 tests:
- Cost-file parser auto-detect header row (cost_v2.xlsx + cost_prod.xlsx).
- ASIN ↔ Merchant SKU mapping endpoints + idempotent re-upload of Amazon PO.
"""
import os
import csv
import io
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ambiance-seller-hub.preview.emergentagent.com").rstrip("/")
SAMPLE = "/app/sample_data"


# --- Cost-file parser tests ----------------------------------------------------

class TestCostParser:
    def test_cost_v2_simple_sheet3_header_row0(self, auth_headers):
        with open(f"{SAMPLE}/cost_v2.xlsx", "rb") as f:
            files = {"file": ("cost_v2.xlsx", f.read(),
                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        r = requests.post(f"{BASE_URL}/api/uploads/costs", files=files, headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "rows_total" in body
        # rows_total should be ~30568 per spec
        assert body["rows_total"] > 25000, f"rows_total too small: {body}"
        assert (body.get("inserted", 0) + body.get("updated", 0)) > 0, body

    def test_cost_prod_legacy_sheet3_header_row2(self, auth_headers):
        with open(f"{SAMPLE}/cost_prod.xlsx", "rb") as f:
            files = {"file": ("cost_prod.xlsx", f.read(),
                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        r = requests.post(f"{BASE_URL}/api/uploads/costs", files=files, headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["rows_total"] > 0, body
        assert (body.get("inserted", 0) + body.get("updated", 0)) > 0, body


# --- ASIN Mapping tests --------------------------------------------------------

@pytest.fixture(scope="module")
def cleanup_test_mappings(auth_headers):
    """Track ASINs uploaded in tests and remove them at end so DB stays clean."""
    yield
    # final cleanup is best-effort via reprocess (no DELETE endpoint exposed for individual mapping is fine,
    # but we want to remove our test mapping to leave DB consistent — not exposed, so skip)


class TestAsinMapping:
    target_asin = "B00PB8WM4S"
    target_merchant = "SAND_116_15x20_white"

    def test_template_csv_has_correct_header_and_asins(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/templates/asin-mapping", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert "text/csv" in r.headers.get("content-type", "")
        text = r.text
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        header = rows[0]
        assert header == ["asin", "merchant_sku", "product_name", "units_sold"], header
        # Should include ~2,037 ASINs
        data_rows = rows[1:]
        assert len(data_rows) > 1500, f"Only {len(data_rows)} ASIN rows in template"
        # Verify target ASIN is present
        asins = {r[0] for r in data_rows}
        assert self.target_asin in asins, f"Target ASIN {self.target_asin} not in template"

    def test_upload_asin_mapping_inserts_and_remaps(self, auth_headers):
        csv_body = "asin,merchant_sku\n" + f"{self.target_asin},{self.target_merchant}\n"
        files = {"file": ("mapping.csv", csv_body.encode("utf-8"), "text/csv")}
        r = requests.post(f"{BASE_URL}/api/uploads/asin-mapping", files=files, headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["rows_total"] == 1, body
        # inserted or updated should be 1 (depending if it ran before)
        assert (body.get("inserted", 0) + body.get("updated", 0)) == 1, body
        assert "orders_remapped" in body
        # If mapping is new (inserted=1), orders_remapped should be >=1.
        # If mapping already existed (updated=1) and orders were already remapped, 0 is correct (idempotent).
        if body.get("inserted", 0) == 1:
            assert body["orders_remapped"] >= 1, f"Expected >=1 orders remapped on fresh apply, got {body}"
        else:
            assert body["orders_remapped"] >= 0, body

    def test_orders_query_returns_mapped_sku_with_asin_preserved(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/orders",
                         params={"sku": self.target_merchant, "limit": 50},
                         headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        items = body.get("items") if isinstance(body, dict) else body
        assert items and len(items) > 0, f"No orders for sku {self.target_merchant}: {body}"
        for o in items:
            assert o.get("sku") == self.target_merchant
            assert o.get("asin") == self.target_asin, f"ASIN preserved? {o}"
            # line_key format: {po_number}::{ASIN} — must end with ASIN (not merchant_sku)
            lk = o.get("line_key") or ""
            assert lk.endswith(f"::{self.target_asin}"), (
                f"line_key must end with ::ASIN to keep re-uploads idempotent, got '{lk}'"
            )

    def test_reupload_amazon_po_is_idempotent_keeps_merchant_sku(self, auth_headers):
        with open(f"{SAMPLE}/amazon_po.xls", "rb") as f:
            files = {"file": ("amazon_po.xls", f.read(), "application/vnd.ms-excel")}
        r = requests.post(f"{BASE_URL}/api/uploads/orders",
                         files=files, headers=auth_headers, data={"source": "amazon_po"})
        assert r.status_code == 200, r.text
        body = r.json()
        # No-op $set returns modified_count=0, so updated may be 0. Key idempotency check:
        # inserted MUST be 0 (no new line_keys created on re-upload).
        assert body.get("inserted", 0) == 0, (
            f"Re-upload created {body.get('inserted')} new rows — line_key is NOT stable. "
            f"This breaks idempotency. Body: {body}"
        )

        # Confirm mapped ASIN still has merchant_sku
        r2 = requests.get(f"{BASE_URL}/api/orders",
                          params={"sku": self.target_merchant, "limit": 10},
                          headers=auth_headers)
        items = r2.json().get("items") if isinstance(r2.json(), dict) else r2.json()
        assert items and items[0].get("sku") == self.target_merchant, "Mapping lost after re-upload"

    def test_admin_reprocess_returns_count(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/admin/reprocess-amazon-asins", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "orders_remapped" in body
        assert isinstance(body["orders_remapped"], int)

    def test_list_mappings_search_case_insensitive(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/asin-mappings", params={"search": "b00"}, headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        items = body if isinstance(body, list) else body.get("items", [])
        assert len(items) >= 1, body
        for m in items:
            assert ("b00" in m["asin"].lower()) or ("b00" in (m.get("merchant_sku") or "").lower())


# --- Regression: ensure totals still 6580 + dedup --------------------------------

class TestOrdersCount:
    def test_orders_count_amazon_no_duplicates(self, auth_headers):
        """Source file has 6,580 lines, all marketplace='Amazon Vendor'. If line_key is stable
        ({po}::ASIN), count must equal 6,580. Any extras = duplicates from line_key rewrite bug."""
        r = requests.get(f"{BASE_URL}/api/orders",
                         params={"marketplaces": "Amazon Vendor", "limit": 1},
                         headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        total = body.get("total")
        assert total == 6580, (
            f"Expected 6580 Amazon Vendor orders, got {total} — duplicates exist "
            f"(line_key was rewritten by apply_asin_mapping to use merchant_sku)."
        )
