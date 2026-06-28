"""
Iteration 9 backend tests covering:
- P&L: shipping income treated as revenue, net excludes shipping subtraction
- Dashboard summary: total_revenue_eur, shipping_income_eur, updated margin
- Amazon Edit Line Items upload (auto-detect, MERGE via PO::ASIN line_key)
- Amazon Delivery view (/dashboard/amazon-delivery + filters + auth)
- Marketplace × Country breakdown
"""
import os
import pytest
import requests

def _load_base():
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if not url:
        env = "/app/frontend/.env"
        if os.path.exists(env):
            for line in open(env):
                if line.startswith("REACT_APP_BACKEND_URL="):
                    url = line.split("=", 1)[1].strip()
                    break
    if not url:
        raise RuntimeError("REACT_APP_BACKEND_URL not set")
    return url.rstrip("/")

BASE = _load_base()
ADMIN_EMAIL = "admin@ambiancesticker.com"
ADMIN_PASSWORD = "Ambiance2026!"


# ---------- fixtures ----------
@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{BASE}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      timeout=20)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="session")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


YTD = {"date_from": "2026-01-01", "date_to": "2026-12-31"}


# ---------- P&L ----------
class TestProfitLoss:
    """Shipping income added to revenue; net profit excludes shipping subtraction."""

    def test_profit_loss_structure_and_math(self, auth_headers):
        r = requests.get(f"{BASE}/api/dashboard/profit-loss",
                         params=YTD, headers=auth_headers, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        # response shape (per-marketplace list)
        rows = data if isinstance(data, list) else (data.get("by_marketplace") or data.get("marketplaces") or data)
        assert isinstance(rows, list) and rows, f"unexpected shape: {data}"
        sample = rows[0]
        required = {"revenue_eur", "shipping_income_eur", "total_revenue_eur",
                    "cogs_eur", "operational_eur", "production_shipping_eur",
                    "commission_eur", "net_profit_eur", "margin_pct"}
        missing = required - set(sample.keys())
        assert not missing, f"missing keys: {missing} in {sample}"
        # math: total_revenue == revenue + shipping_income
        for row in rows:
            tr = row["total_revenue_eur"]
            calc = row["revenue_eur"] + row["shipping_income_eur"]
            assert abs(tr - calc) < 0.05, f"total_revenue mismatch: {row}"
            # net = total - cogs - operational - prod_shipping - commission  (no subtract of shipping_income)
            net_calc = (tr - row["cogs_eur"] - row["operational_eur"]
                        - row["production_shipping_eur"] - row["commission_eur"])
            assert abs(row["net_profit_eur"] - net_calc) < 0.05, \
                f"net mismatch: {row}"

    def test_profit_loss_leroy_merlin_values(self, auth_headers):
        r = requests.get(f"{BASE}/api/dashboard/profit-loss",
                         params=YTD, headers=auth_headers, timeout=20)
        body = r.json()
        rows = body if isinstance(body, list) else (body.get("by_marketplace") or body.get("marketplaces") or body)
        lm = next((x for x in rows if "leroy" in x.get("marketplace", "").lower()), None)
        assert lm, "Leroy Merlin row missing"
        assert abs(lm["revenue_eur"] - 41682.66) < 2.0, lm
        assert abs(lm["shipping_income_eur"] - 5636.79) < 2.0, lm
        assert abs(lm["total_revenue_eur"] - 47319.45) < 3.0, lm
        assert abs(lm["net_profit_eur"] - 20827.64) < 50.0, lm  # tolerance for cost rates


# ---------- Dashboard summary ----------
class TestDashboardSummary:
    def test_summary_has_total_and_shipping_income(self, auth_headers):
        r = requests.get(f"{BASE}/api/dashboard/summary",
                         params=YTD, headers=auth_headers, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "total_revenue_eur" in d, d.keys()
        assert "shipping_income_eur" in d, d.keys()
        assert isinstance(d["total_revenue_eur"], (int, float))
        # margin against total revenue, shipping not subtracted
        if "margin_pct" in d and d["total_revenue_eur"]:
            cogs = d.get("cogs_eur", 0)
            opex = d.get("operational_cost_eur", d.get("operational_eur", 0))
            prod_sh = d.get("production_shipping_eur", 0)
            comm = d.get("commission_eur", 0)
            calc_margin = (d["total_revenue_eur"] - cogs - opex - prod_sh - comm) / d["total_revenue_eur"] * 100
            assert abs(d["margin_pct"] - calc_margin) < 1.5, d


# ---------- Amazon Edit upload ----------
class TestAmazonEditUpload:
    def test_upload_auto_detect_and_merge(self, auth_headers):
        path = "/tmp/edit_line_items.xlsx"
        assert os.path.exists(path), "sample file missing"
        with open(path, "rb") as f:
            files = {"file": ("edit_line_items.xlsx", f,
                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
            data = {"source": "auto"}
            r = requests.post(f"{BASE}/api/uploads/orders",
                              files=files, data=data,
                              headers=auth_headers, timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("source") == "amazon_edit", body
        assert body.get("rows_total", 0) >= 1, body


# ---------- Amazon Delivery view ----------
class TestAmazonDelivery:
    def test_requires_auth(self):
        r = requests.get(f"{BASE}/api/dashboard/amazon-delivery", timeout=20)
        assert r.status_code == 401, r.status_code

    def test_returns_shape(self, auth_headers):
        r = requests.get(f"{BASE}/api/dashboard/amazon-delivery",
                         headers=auth_headers, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "totals" in d and "timeline" in d and "pos" in d, d.keys()
        t = d["totals"]
        for k in ("pos", "units", "revenue_eur", "delivery_lines"):
            assert k in t, f"totals missing {k}"
        if d["pos"]:
            p = d["pos"][0]
            for k in ("po", "delivery_date", "window_start", "order_date",
                      "warehouse", "status", "units", "lines", "revenue_eur"):
                assert k in p, f"pos row missing {k}: {p}"

    def test_filter_delivery_window(self, auth_headers):
        r = requests.get(f"{BASE}/api/dashboard/amazon-delivery",
                         params={"delivery_from": "2026-07-01",
                                 "delivery_to": "2026-07-31"},
                         headers=auth_headers, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        for p in d["pos"]:
            dd = p["delivery_date"]
            assert dd and "2026-07" in dd, f"delivery outside window: {dd}"

    def test_order_date_differs_from_delivery(self, auth_headers):
        r = requests.get(f"{BASE}/api/dashboard/amazon-delivery",
                         headers=auth_headers, timeout=20)
        rows = r.json().get("pos", [])
        if not rows:
            pytest.skip("no PO rows to compare")
        differ = sum(1 for p in rows if p.get("order_date") and p.get("delivery_date")
                     and p["order_date"] != p["delivery_date"])
        assert differ >= 1, "expected at least one PO with order_date != delivery_date"


# ---------- Marketplace × Country ----------
class TestMarketplaceCountry:
    def test_endpoint_shape(self, auth_headers):
        r = requests.get(f"{BASE}/api/dashboard/marketplace-country-breakdown",
                         params=YTD, headers=auth_headers, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        rows = data if isinstance(data, list) else data.get("by_marketplace", data.get("data", []))
        assert isinstance(rows, list) and rows, data
        for k in ("marketplace", "revenue_eur", "countries"):
            assert k in rows[0], rows[0].keys()
        assert isinstance(rows[0]["countries"], list)

    def test_leroy_merlin_country_sum(self, auth_headers):
        r = requests.get(f"{BASE}/api/dashboard/marketplace-country-breakdown",
                         params=YTD, headers=auth_headers, timeout=30)
        rows = r.json() if isinstance(r.json(), list) else r.json().get("by_marketplace", [])
        lm = next((x for x in rows if "leroy" in x.get("marketplace", "").lower()), None)
        assert lm, "Leroy Merlin row missing"
        sum_countries = sum(c["revenue_eur"] for c in lm["countries"])
        assert abs(sum_countries - lm["revenue_eur"]) < 2.0, \
            f"country sum {sum_countries} != marketplace {lm['revenue_eur']}"
        codes = {c["country"] for c in lm["countries"]}
        # should at least include FR, ES, IT, PT
        assert "FR" in codes or "France" in codes, codes
        assert len(codes) >= 4, codes

    def test_filter_by_marketplace(self, auth_headers):
        r = requests.get(f"{BASE}/api/dashboard/marketplace-country-breakdown",
                         params={**YTD, "marketplaces": "Leroy Merlin"},
                         headers=auth_headers, timeout=30)
        assert r.status_code == 200, r.text
        rows = r.json() if isinstance(r.json(), list) else r.json().get("by_marketplace", [])
        assert len(rows) == 1, rows
        assert "leroy" in rows[0]["marketplace"].lower()


# ---------- Regression: critical GETs still work ----------
class TestRegression:
    @pytest.mark.parametrize("path", [
        "/api/auth/me",
        "/api/dashboard/summary",
        "/api/dashboard/profit-loss",
        "/api/dashboard/returns",
        "/api/dashboard/marketplace-country-breakdown",
        "/api/dashboard/amazon-delivery",
        "/api/orders",
        "/api/marketplaces",
        "/api/library/loss-makers",
        "/api/uploads/history",
    ])
    def test_get_200(self, auth_headers, path):
        r = requests.get(f"{BASE}{path}", params=YTD, headers=auth_headers, timeout=30)
        assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:200]}"
