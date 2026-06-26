"""Iteration 8 tests: admin-role guard, returns endpoint, refactor regression."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://ambiance-seller-hub.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = "admin@ambiancesticker.com"
ADMIN_PASSWORD = "Ambiance2026!"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    data = r.json()
    return data.get("token") or data.get("access_token")


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ------------------- Admin guard: unauthenticated 401 -------------------
ADMIN_WRITE_ENDPOINTS = [
    ("POST", "/api/uploads/orders"),
    ("POST", "/api/uploads/costs"),
    ("POST", "/api/uploads/asin-mapping"),
    ("PUT", "/api/cost-constants"),
    ("PUT", "/api/exchange-rates"),
    ("POST", "/api/admin/renormalize-marketplaces"),
    ("POST", "/api/admin/reprocess-amazon-asins"),
    ("POST", "/api/costs/manual"),
    ("DELETE", "/api/costs/TEST_NONEXISTENT_SKU"),
]


@pytest.mark.parametrize("method,path", ADMIN_WRITE_ENDPOINTS)
def test_admin_endpoint_unauthenticated_returns_401(method, path):
    r = requests.request(method, f"{BASE_URL}{path}", json={}, timeout=15)
    assert r.status_code == 401, f"{method} {path} expected 401, got {r.status_code}: {r.text[:200]}"


# ------------------- Admin guard: authenticated admin succeeds -------------------
def test_put_cost_constants_admin_ok(auth_headers):
    # GET current state to restore later
    g = requests.get(f"{BASE_URL}/api/cost-constants", headers=auth_headers, timeout=15)
    assert g.status_code == 200
    current = g.json()
    payload = {
        "operational_cost_per_unit": float(current.get("operational_cost_per_unit", 0.5)),
        "production_shipping_by_marketplace": current.get("production_shipping_by_marketplace", {}),
        "commission_by_marketplace": current.get("commission_by_marketplace", {}),
    }
    r = requests.put(f"{BASE_URL}/api/cost-constants", json=payload, headers=auth_headers, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "operational_cost_per_unit" in data


def test_put_exchange_rates_admin_ok(auth_headers):
    g = requests.get(f"{BASE_URL}/api/exchange-rates", headers=auth_headers, timeout=15)
    assert g.status_code == 200
    rates = g.json()
    r = requests.put(f"{BASE_URL}/api/exchange-rates", json={"rates": rates}, headers=auth_headers, timeout=60)
    assert r.status_code == 200, r.text
    assert r.json().get("EUR") == 1.0


def test_post_costs_manual_admin_ok(auth_headers):
    payload = {
        "sku": "TEST_ITER8_SKU",
        "product_name": "Iter8 Test",
        "cost_per_unit": 1.23,
        "shipping_cost": 0.45,
        "currency": "EUR",
    }
    r = requests.post(f"{BASE_URL}/api/costs/manual", json=payload, headers=auth_headers, timeout=15)
    assert r.status_code == 200, r.text
    # cleanup
    d = requests.delete(f"{BASE_URL}/api/costs/TEST_ITER8_SKU", headers=auth_headers, timeout=15)
    assert d.status_code == 200


def test_delete_costs_admin_ok(auth_headers):
    # ensure deletion of non-existent returns OK and is authorized
    r = requests.delete(f"{BASE_URL}/api/costs/TEST_DOES_NOT_EXIST_XYZ", headers=auth_headers, timeout=15)
    assert r.status_code == 200


# ------------------- GET regression: still require only auth -------------------
GET_ENDPOINTS_AUTH_ONLY = [
    "/api/cost-constants",
    "/api/exchange-rates",
    "/api/costs",
    "/api/uploads/history",
    "/api/asin-mappings",
    "/api/marketplaces",
]


@pytest.mark.parametrize("path", GET_ENDPOINTS_AUTH_ONLY)
def test_get_endpoints_with_auth_200(path, auth_headers):
    r = requests.get(f"{BASE_URL}{path}", headers=auth_headers, timeout=20)
    assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"


@pytest.mark.parametrize("path", GET_ENDPOINTS_AUTH_ONLY)
def test_get_endpoints_without_auth_401(path):
    r = requests.get(f"{BASE_URL}{path}", timeout=15)
    assert r.status_code == 401, f"{path} expected 401 without auth, got {r.status_code}"


# ------------------- /api/dashboard/returns -------------------
def test_returns_requires_auth():
    r = requests.get(f"{BASE_URL}/api/dashboard/returns", timeout=15)
    assert r.status_code == 401


def test_returns_shape_and_totals(auth_headers):
    r = requests.get(
        f"{BASE_URL}/api/dashboard/returns",
        headers=auth_headers,
        params={"date_from": "2026-01-01", "date_to": "2026-12-31"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert set(data.keys()) >= {"by_marketplace", "totals", "recent"}
    assert isinstance(data["by_marketplace"], list)
    assert isinstance(data["recent"], list)
    t = data["totals"]
    expected_total_keys = {
        "refund_eur", "refund_units", "refund_orders",
        "cancel_eur", "cancel_units", "cancel_orders",
        "refund_rate_pct", "cancel_rate_pct",
        "total_revenue_eur", "total_units",
    }
    assert expected_total_keys.issubset(set(t.keys())), f"Missing keys: {expected_total_keys - set(t.keys())}"
    # Spec: refund_eur ~ 1516.59 (allow small drift)
    assert abs(t["refund_eur"] - 1516.59) < 5.0, f"refund_eur drift: {t['refund_eur']}"
    # Spec: 6 marketplaces in by_marketplace (allow ±2)
    assert 4 <= len(data["by_marketplace"]) <= 10, f"by_marketplace count={len(data['by_marketplace'])}"


def test_returns_marketplace_filter(auth_headers):
    r = requests.get(
        f"{BASE_URL}/api/dashboard/returns",
        headers=auth_headers,
        params={"date_from": "2026-01-01", "date_to": "2026-12-31", "marketplaces": "Mano Mano"},
        timeout=30,
    )
    assert r.status_code == 200
    data = r.json()
    for row in data["by_marketplace"]:
        assert row["marketplace"] == "Mano Mano"


# ------------------- Refactor regression: all endpoints respond -------------------
REGRESSION_GET_ENDPOINTS = [
    "/api/auth/me",
    "/api/dashboard/summary",
    "/api/dashboard/trend",
    "/api/dashboard/marketplace-breakdown",
    "/api/dashboard/top-skus",
    "/api/dashboard/customers",
    "/api/dashboard/heatmap",
    "/api/dashboard/profit-loss",
    "/api/orders",
    "/api/orders/export",
    "/api/library/skus",
    "/api/library/export",
    "/api/library/loss-makers",
    "/api/marketplaces",
    "/api/skus",
    "/api/skus/prices",
    "/api/skus/prices/export",
    "/api/uploads/history",
    "/api/asin-mappings",
    "/api/templates/cost",
    "/api/templates/asin-mapping",
]


@pytest.mark.parametrize("path", REGRESSION_GET_ENDPOINTS)
def test_regression_endpoint_responds(path, auth_headers):
    r = requests.get(f"{BASE_URL}{path}", headers=auth_headers, timeout=60)
    assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:200]}"


def test_dashboard_summary_value(auth_headers):
    r = requests.get(f"{BASE_URL}/api/dashboard/summary", headers=auth_headers, timeout=30)
    assert r.status_code == 200
    data = r.json()
    # Spec: total revenue ~ 119906.19
    assert abs(data["revenue_eur"] - 119906.19) < 50.0, f"revenue drift: {data['revenue_eur']}"


def test_library_loss_makers_count(auth_headers):
    r = requests.get(f"{BASE_URL}/api/library/loss-makers", headers=auth_headers, timeout=30)
    assert r.status_code == 200
    data = r.json()
    # Could be {"summary":..,"rows":..} or list
    rows = data if isinstance(data, list) else data.get("rows") or data.get("loss_makers") or []
    assert len(rows) >= 50, f"loss_makers count={len(rows)}"


def test_auth_login_and_me(auth_headers):
    r = requests.get(f"{BASE_URL}/api/auth/me", headers=auth_headers, timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert data.get("email") == ADMIN_EMAIL
    assert data.get("role") == "admin"
