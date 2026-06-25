"""Iteration 3 tests: cost constants, library, P&L and summary new fields."""
import requests
import pytest
from conftest import BASE_URL


# --------- /api/cost-constants ---------
class TestCostConstants:
    def test_get_cost_constants_default(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/cost-constants", headers=auth_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "operational_cost_per_unit" in d
        assert "production_shipping_by_marketplace" in d
        assert isinstance(d["production_shipping_by_marketplace"], dict)

    def test_put_cost_constants_persists(self, auth_headers):
        payload = {
            "operational_cost_per_unit": 0.6,
            "production_shipping_by_marketplace": {"Amazon Vendor": 0.3, "BOL.COM": 0.5},
        }
        r = requests.put(f"{BASE_URL}/api/cost-constants", headers=auth_headers, json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert abs(d["operational_cost_per_unit"] - 0.6) < 1e-6
        assert d["production_shipping_by_marketplace"].get("Amazon Vendor") == 0.3
        assert d["production_shipping_by_marketplace"].get("BOL.COM") == 0.5

        # GET to verify persistence
        r2 = requests.get(f"{BASE_URL}/api/cost-constants", headers=auth_headers)
        d2 = r2.json()
        assert abs(d2["operational_cost_per_unit"] - 0.6) < 1e-6
        assert d2["production_shipping_by_marketplace"].get("Amazon Vendor") == 0.3

        # Reset to original spec defaults for next tests (op=0.5, mk={Amazon Vendor:0.3, Leroy Merlin:0.4, BOL.COM:0.5})
        reset = {
            "operational_cost_per_unit": 0.5,
            "production_shipping_by_marketplace": {
                "Amazon Vendor": 0.3,
                "Leroy Merlin": 0.4,
                "BOL.COM": 0.5,
            },
        }
        r3 = requests.put(f"{BASE_URL}/api/cost-constants", headers=auth_headers, json=reset)
        assert r3.status_code == 200


# --------- /api/dashboard/profit-loss ---------
class TestProfitLossNewFields:
    def test_pnl_has_new_fields_and_math(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/dashboard/profit-loss", headers=auth_headers)
        assert r.status_code == 200, r.text
        rows = r.json()
        assert isinstance(rows, list)
        assert len(rows) > 0
        for row in rows:
            for k in ("marketplace", "revenue_eur", "cogs_eur", "shipping_eur",
                      "operational_eur", "production_shipping_eur", "net_profit_eur", "units"):
                assert k in row, f"missing {k} in P&L row {row}"
            # net_profit = revenue - cogs - shipping - operational - prod_shipping (tolerance for rounding)
            expected = (row["revenue_eur"] - row["cogs_eur"] - row["shipping_eur"]
                        - row["operational_eur"] - row["production_shipping_eur"])
            assert abs(row["net_profit_eur"] - round(expected, 2)) < 0.05, (
                f"net_profit_eur mismatch for {row['marketplace']}: "
                f"got {row['net_profit_eur']} expected {round(expected, 2)}"
            )

    def test_pnl_operational_matches_units_times_cost(self, auth_headers):
        # Get cost constants
        cc = requests.get(f"{BASE_URL}/api/cost-constants", headers=auth_headers).json()
        op_cost = cc["operational_cost_per_unit"]
        mk_ship = cc["production_shipping_by_marketplace"]
        rows = requests.get(f"{BASE_URL}/api/dashboard/profit-loss", headers=auth_headers).json()
        for row in rows:
            units = row["units"]
            expected_op = round(op_cost * units, 2)
            assert abs(row["operational_eur"] - expected_op) < 0.05, (
                f"operational_eur for {row['marketplace']} expected {expected_op} got {row['operational_eur']}"
            )
            expected_ship = round(float(mk_ship.get(row["marketplace"], 0)) * units, 2)
            assert abs(row["production_shipping_eur"] - expected_ship) < 0.05, (
                f"production_shipping_eur for {row['marketplace']} expected {expected_ship} got {row['production_shipping_eur']}"
            )


# --------- /api/dashboard/summary new fields ---------
class TestSummaryNewFields:
    def test_summary_has_new_cost_fields(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/dashboard/summary", headers=auth_headers)
        assert r.status_code == 200
        d = r.json()
        assert "operational_eur" in d
        assert "production_shipping_eur" in d
        assert d["operational_eur"] >= 0
        assert d["production_shipping_eur"] >= 0

    def test_summary_margin_includes_all_costs(self, auth_headers):
        d = requests.get(f"{BASE_URL}/api/dashboard/summary", headers=auth_headers).json()
        revenue = d["revenue_eur"]
        total_costs = d["cogs_eur"] + d["shipping_eur"] + d["operational_eur"] + d["production_shipping_eur"]
        expected_margin = revenue - total_costs
        assert abs(d["margin_eur"] - round(expected_margin, 2)) < 0.05
        if revenue > 0:
            expected_pct = round(expected_margin / revenue * 100, 2)
            assert abs(d["margin_pct"] - expected_pct) < 0.05


# --------- /api/library/skus ---------
class TestLibrarySkus:
    def test_library_skus_basic(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/library/skus", headers=auth_headers, params={"limit": 50})
        assert r.status_code == 200, r.text
        rows = r.json()
        assert isinstance(rows, list)
        assert len(rows) > 0
        sample = rows[0]
        for k in ("sku", "product_name", "production_cost", "operational_cost",
                  "production_shipping_cost", "total_cost", "units_sold", "has_cost"):
            assert k in sample, f"missing key {k} in library row"
        # operational_cost matches constants
        cc = requests.get(f"{BASE_URL}/api/cost-constants", headers=auth_headers).json()
        op_cost = cc["operational_cost_per_unit"]
        assert abs(sample["operational_cost"] - op_cost) < 1e-3

    def test_library_search_filter(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/library/skus", headers=auth_headers,
                         params={"search": "privacy", "limit": 500})
        assert r.status_code == 200
        rows = r.json()
        for row in rows:
            text = (row["sku"] + " " + (row["product_name"] or "")).lower()
            assert "privacy" in text, f"Row {row['sku']} ({row['product_name']}) does not contain 'privacy'"

    def test_library_total_cost_math(self, auth_headers):
        rows = requests.get(f"{BASE_URL}/api/library/skus", headers=auth_headers,
                            params={"limit": 100}).json()
        for r in rows[:20]:
            expected_total = round(r["production_cost"] + r["operational_cost"] + r["production_shipping_cost"], 4)
            assert abs(r["total_cost"] - expected_total) < 1e-3, (
                f"total_cost mismatch for {r['sku']}: got {r['total_cost']} expected {expected_total}"
            )


# --------- /api/library/export ---------
class TestLibraryExport:
    def test_library_export_csv(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/library/export", headers=auth_headers, timeout=120)
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")
        lines = r.text.splitlines()
        assert len(lines) >= 1
        expected_header = "SKU,Product,Production Cost (EUR),Operational Cost (EUR),Production Shipping Cost (EUR),Total Cost (EUR),Units Sold"
        assert lines[0] == expected_header, f"Unexpected header: {lines[0]}"
        assert len(lines) > 1, "Library export has no data rows"
