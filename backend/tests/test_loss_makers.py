"""Iteration 7 backend tests — Loss-Making SKUs view.

Validates:
- GET /api/library/loss-makers returns 200, expected shape, net_per_unit <= 0,
  rows sorted by total_loss_eur ascending (most negative first).
- Query filters: date_from/date_to + marketplaces (comma separated).
- JWT required (401 without token).
- Regression: dashboard, products, prices, library, p&l, uploads, settings, login.
"""
import os
import re
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://ambiance-seller-hub.preview.emergentagent.com").rstrip("/")


# -------- Loss-Makers endpoint --------
class TestLossMakers:
    REQUIRED_KEYS = {
        "sku", "marketplace", "product_name", "units",
        "avg_unit_price", "production_cost", "operational_cost",
        "production_shipping", "commission_per_unit", "total_cost_per_unit",
        "net_per_unit", "total_loss_eur",
    }

    def test_requires_jwt(self):
        r = requests.get(f"{BASE}/api/library/loss-makers", timeout=30)
        assert r.status_code in (401, 403), f"Expected 401/403 without token, got {r.status_code}"

    def test_returns_200_with_token(self, auth_headers):
        r = requests.get(f"{BASE}/api/library/loss-makers", headers=auth_headers, timeout=60)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_row_shape(self, auth_headers):
        r = requests.get(f"{BASE}/api/library/loss-makers", headers=auth_headers, timeout=60)
        rows = r.json()
        if not rows:
            pytest.skip("No loss-making rows in current DB state")
        sample = rows[0]
        missing = self.REQUIRED_KEYS - set(sample.keys())
        assert missing == set(), f"Missing keys in row: {missing}; got: {list(sample.keys())}"

    def test_net_per_unit_non_positive(self, auth_headers):
        r = requests.get(f"{BASE}/api/library/loss-makers", headers=auth_headers, timeout=60)
        rows = r.json()
        for row in rows:
            assert row["net_per_unit"] <= 0, f"net_per_unit must be <= 0: {row}"

    def test_sorted_by_total_loss_ascending(self, auth_headers):
        r = requests.get(f"{BASE}/api/library/loss-makers", headers=auth_headers, timeout=60)
        rows = r.json()
        if len(rows) < 2:
            pytest.skip("Need >=2 rows to verify sort order")
        losses = [row["total_loss_eur"] for row in rows]
        assert losses == sorted(losses), f"Rows not sorted ascending by total_loss_eur: first 5={losses[:5]}"
        # First (most negative) should be smallest
        assert losses[0] == min(losses)

    def test_marketplace_filter_single(self, auth_headers):
        # First fetch all to discover a marketplace that has loss rows
        all_r = requests.get(f"{BASE}/api/library/loss-makers", headers=auth_headers, timeout=60).json()
        if not all_r:
            pytest.skip("No loss rows to filter")
        target_mk = all_r[0]["marketplace"]
        r = requests.get(
            f"{BASE}/api/library/loss-makers",
            headers=auth_headers, params={"marketplaces": target_mk}, timeout=60,
        )
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) > 0
        for row in rows:
            assert row["marketplace"] == target_mk, f"Filter leaked other marketplace: {row['marketplace']}"

    def test_date_range_filter(self, auth_headers):
        # Wide range should return at least as many rows as a narrow range
        wide = requests.get(
            f"{BASE}/api/library/loss-makers",
            headers=auth_headers,
            params={"date_from": "2020-01-01", "date_to": "2030-12-31"},
            timeout=60,
        )
        assert wide.status_code == 200
        narrow = requests.get(
            f"{BASE}/api/library/loss-makers",
            headers=auth_headers,
            params={"date_from": "2099-01-01", "date_to": "2099-12-31"},
            timeout=60,
        )
        assert narrow.status_code == 200
        # Narrow future window should be empty
        assert narrow.json() == [] or len(narrow.json()) <= len(wide.json())

    def test_cost_math_consistency(self, auth_headers):
        """total_cost_per_unit ~= prod + op + ship + commission, net = avg - total_cost."""
        r = requests.get(f"{BASE}/api/library/loss-makers", headers=auth_headers, timeout=60)
        rows = r.json()
        if not rows:
            pytest.skip("No rows")
        for row in rows[:10]:
            expected_total = (
                row["production_cost"] + row["operational_cost"]
                + row["production_shipping"] + row["commission_per_unit"]
            )
            assert abs(row["total_cost_per_unit"] - expected_total) < 0.05, (
                f"total_cost mismatch: row={row}, expected~{expected_total}"
            )
            expected_net = row["avg_unit_price"] - row["total_cost_per_unit"]
            assert abs(row["net_per_unit"] - expected_net) < 0.05, (
                f"net_per_unit mismatch: row={row}, expected~{expected_net}"
            )
            # total_loss should equal net * units (approx)
            expected_loss = row["net_per_unit"] * row["units"]
            assert abs(row["total_loss_eur"] - expected_loss) < max(1.0, abs(expected_loss) * 0.02), (
                f"total_loss mismatch: row={row}, expected~{expected_loss}"
            )


# -------- Regression smoke tests for prior pages --------
class TestRegression:
    def test_login(self):
        r = requests.post(
            f"{BASE}/api/auth/login",
            json={"email": "admin@ambiancesticker.com", "password": "Ambiance2026!"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert "token" in d and isinstance(d["token"], str)

    def test_dashboard_summary(self, auth_headers):
        r = requests.get(f"{BASE}/api/dashboard/summary", headers=auth_headers, timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d.get("revenue_eur", 0) > 0
        assert d.get("cogs_eur", 0) > 0

    def test_dashboard_top_skus(self, auth_headers):
        r = requests.get(f"{BASE}/api/dashboard/top-skus", headers=auth_headers, timeout=30)
        assert r.status_code == 200
        assert isinstance(r.json(), list) and len(r.json()) > 0

    def test_products(self, auth_headers):
        # Products page is fed by /api/skus
        r = requests.get(f"{BASE}/api/skus", headers=auth_headers, timeout=60)
        assert r.status_code == 200

    def test_prices(self, auth_headers):
        # Prices page → /api/skus/prices
        r = requests.get(f"{BASE}/api/skus/prices", headers=auth_headers, timeout=60)
        assert r.status_code == 200

    def test_library(self, auth_headers):
        r = requests.get(f"{BASE}/api/library/skus", headers=auth_headers, timeout=60)
        assert r.status_code == 200

    def test_pnl(self, auth_headers):
        # P&L page → /api/dashboard/profit-loss
        r = requests.get(f"{BASE}/api/dashboard/profit-loss", headers=auth_headers, timeout=60)
        assert r.status_code == 200, f"P&L failed: {r.status_code} {r.text[:200]}"

    def test_uploads_list(self, auth_headers):
        r = requests.get(f"{BASE}/api/uploads/history", headers=auth_headers, timeout=30)
        assert r.status_code == 200

    def test_settings_cost_constants(self, auth_headers):
        r = requests.get(f"{BASE}/api/cost-constants", headers=auth_headers, timeout=30)
        assert r.status_code == 200
