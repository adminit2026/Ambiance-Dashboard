"""End-to-end backend tests for Ambiance Analytics Hub."""
import io
import os
import csv
import requests
import pytest

from conftest import BASE_URL, ADMIN_EMAIL, ADMIN_PASSWORD

SAMPLE_DIR = "/app/sample_data"


# --------------- AUTH ---------------
class TestAuth:
    def test_login_success(self, api_client):
        r = api_client.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r.status_code == 200, r.text
        d = r.json()
        assert "token" in d and isinstance(d["token"], str) and len(d["token"]) > 20
        assert d["user"]["email"] == ADMIN_EMAIL

    def test_login_invalid(self, api_client):
        r = api_client.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong"})
        assert r.status_code == 401

    def test_me_requires_auth(self, api_client):
        r = requests.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 401

    def test_me_with_token(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["email"] == ADMIN_EMAIL


# --------------- UPLOADS (orders + costs) ---------------
class TestUploads:
    def test_upload_channelengine(self, auth_headers):
        path = os.path.join(SAMPLE_DIR, "channelengine.csv")
        with open(path, "rb") as f:
            r = requests.post(
                f"{BASE_URL}/api/uploads/orders",
                headers=auth_headers,
                files={"file": ("channelengine.csv", f, "text/csv")},
                data={"source": "auto"},
            )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["source"] == "channelengine"
        assert d["rows_total"] > 0
        assert "inserted" in d and "updated" in d

    def test_upload_beezup(self, auth_headers):
        path = os.path.join(SAMPLE_DIR, "beezup.xlsx")
        with open(path, "rb") as f:
            r = requests.post(
                f"{BASE_URL}/api/uploads/orders",
                headers=auth_headers,
                files={"file": ("beezup.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                data={"source": "auto"},
            )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["source"] == "beezup"
        assert d["rows_total"] > 0

    def test_upload_amazon_po(self, auth_headers):
        path = os.path.join(SAMPLE_DIR, "amazon_po.xls")
        with open(path, "rb") as f:
            r = requests.post(
                f"{BASE_URL}/api/uploads/orders",
                headers=auth_headers,
                files={"file": ("amazon_po.xls", f, "application/vnd.ms-excel")},
                data={"source": "auto"},
            )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["source"] == "amazon_po"
        assert d["rows_total"] > 0

    def test_upload_channelengine_idempotent(self, auth_headers):
        """Second upload of same file should not insert duplicates."""
        path = os.path.join(SAMPLE_DIR, "channelengine.csv")
        with open(path, "rb") as f:
            r = requests.post(
                f"{BASE_URL}/api/uploads/orders",
                headers=auth_headers,
                files={"file": ("channelengine.csv", f, "text/csv")},
                data={"source": "auto"},
            )
        assert r.status_code == 200
        d = r.json()
        # re-upload: inserted should be 0 (everything already exists)
        assert d["inserted"] == 0, f"Expected idempotent re-upload, got inserted={d['inserted']}"

    def test_upload_costs_valid(self, auth_headers):
        csv_content = "sku,cost_per_unit,shipping_cost,currency\nTEST_SKU_001,1.50,0.30,EUR\nTEST_SKU_002,2.25,0.40,EUR\n"
        r = requests.post(
            f"{BASE_URL}/api/uploads/costs",
            headers=auth_headers,
            files={"file": ("costs.csv", io.BytesIO(csv_content.encode()), "text/csv")},
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["rows_total"] == 2

    def test_upload_costs_malformed(self, auth_headers):
        bad = "wrongcol,foo\nx,1\n"
        r = requests.post(
            f"{BASE_URL}/api/uploads/costs",
            headers=auth_headers,
            files={"file": ("bad.csv", io.BytesIO(bad.encode()), "text/csv")},
        )
        assert r.status_code == 400
        assert "detail" in r.json()

    def test_uploads_history(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/uploads/history", headers=auth_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        assert len(r.json()) > 0


# --------------- DASHBOARD ---------------
class TestDashboard:
    def test_summary(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/dashboard/summary", headers=auth_headers)
        assert r.status_code == 200
        d = r.json()
        for k in ("revenue_eur", "orders", "units", "aov_eur", "margin_pct", "cogs_eur"):
            assert k in d
        assert d["revenue_eur"] > 0
        assert d["orders"] > 0

    def test_summary_with_date_filter(self, auth_headers):
        r = requests.get(
            f"{BASE_URL}/api/dashboard/summary",
            headers=auth_headers,
            params={"date_from": "2025-01-01", "date_to": "2025-12-31"},
        )
        assert r.status_code == 200

    def test_trend_day(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/dashboard/trend", headers=auth_headers, params={"granularity": "day"})
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        if data:
            assert "period" in data[0] and "by_marketplace" in data[0]

    def test_trend_month(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/dashboard/trend", headers=auth_headers, params={"granularity": "month"})
        assert r.status_code == 200

    def test_marketplace_breakdown(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/dashboard/marketplace-breakdown", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list) and len(data) > 0
        assert "marketplace" in data[0] and "revenue_eur" in data[0] and "aov_eur" in data[0]

    def test_top_skus(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/dashboard/top-skus", headers=auth_headers, params={"limit": 5})
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        if data:
            assert "sku" in data[0] and "has_cost" in data[0]

    def test_customers(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/dashboard/customers", headers=auth_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_profit_loss(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/dashboard/profit-loss", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        if data:
            assert "marketplace" in data[0] and "net_profit_eur" in data[0]

    def test_heatmap(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/dashboard/heatmap", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        if data:
            assert "date" in data[0] and "revenue_eur" in data[0]


# --------------- ORDERS LIST + EXPORT ---------------
class TestOrders:
    def test_list_orders(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/orders", headers=auth_headers, params={"limit": 10})
        assert r.status_code == 200
        d = r.json()
        assert "total" in d and "items" in d
        assert d["total"] > 0

    def test_list_orders_filtered(self, auth_headers):
        r = requests.get(
            f"{BASE_URL}/api/orders",
            headers=auth_headers,
            params={"date_from": "2025-01-01", "date_to": "2025-12-31", "limit": 5},
        )
        assert r.status_code == 200

    def test_export_csv(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/orders/export", headers=auth_headers, params={"limit": 5})
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")
        content = r.text.splitlines()
        assert len(content) > 1
        # Verify header row
        first = content[0]
        for col in ("order_date_iso", "marketplace", "sku", "line_total_eur"):
            assert col in first


# --------------- MARKETPLACES + EXCHANGE RATES + COSTS ---------------
class TestMisc:
    def test_marketplaces(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/marketplaces", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert "Amazon Vendor" in data

    def test_exchange_rates_get(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/exchange-rates", headers=auth_headers)
        assert r.status_code == 200
        d = r.json()
        assert d.get("EUR") == 1.0

    def test_exchange_rates_put_recompute(self, auth_headers):
        # Get baseline summary
        r0 = requests.get(f"{BASE_URL}/api/dashboard/summary", headers=auth_headers)
        baseline_rev = r0.json()["revenue_eur"]

        # Get current rates
        cur = requests.get(f"{BASE_URL}/api/exchange-rates", headers=auth_headers).json()
        original_usd = cur.get("USD", 0.92)

        # Change USD to 2.0
        new_rates = dict(cur)
        new_rates["USD"] = 2.0
        r = requests.put(f"{BASE_URL}/api/exchange-rates", headers=auth_headers, json={"rates": new_rates})
        assert r.status_code == 200
        assert r.json()["USD"] == 2.0

        # Revert
        new_rates["USD"] = original_usd
        r2 = requests.put(f"{BASE_URL}/api/exchange-rates", headers=auth_headers, json={"rates": new_rates})
        assert r2.status_code == 200

        # Summary should be close to baseline
        r3 = requests.get(f"{BASE_URL}/api/dashboard/summary", headers=auth_headers)
        assert abs(r3.json()["revenue_eur"] - baseline_rev) < 1.0

    def test_manual_cost_add(self, auth_headers):
        r = requests.post(
            f"{BASE_URL}/api/costs/manual",
            headers=auth_headers,
            json={"sku": "TEST_MANUAL_001", "product_name": "Test", "cost_per_unit": 2.0, "shipping_cost": 0.5, "currency": "EUR"},
        )
        assert r.status_code == 200
        # verify
        r2 = requests.get(f"{BASE_URL}/api/costs", headers=auth_headers)
        assert r2.status_code == 200
        skus = [c["sku"] for c in r2.json()]
        assert "TEST_MANUAL_001" in skus

    def test_manual_cost_cleanup(self, auth_headers):
        for sku in ("TEST_MANUAL_001", "TEST_SKU_001", "TEST_SKU_002"):
            requests.delete(f"{BASE_URL}/api/costs/{sku}", headers=auth_headers)
