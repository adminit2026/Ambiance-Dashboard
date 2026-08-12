"""Iteration 10 - Margin parity regression + Products page overflow fix support."""
import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback to frontend env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

CREDS = {"email": "admin@ambiancesticker.com", "password": "Ambiance2026!"}


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json=CREDS, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_margin_parity_leroy_merlin_es(auth):
    """sum(margin)/sum(total_revenue) from top-skus must match profit-loss margin_pct within 0.1%."""
    params = {
        "date_from": "2025-01-01",
        "date_to": "2026-12-31",
        "marketplaces": "Leroy Merlin - ES",
    }
    r_skus = requests.get(
        f"{BASE_URL}/api/dashboard/top-skus",
        params={**params, "limit": 20000},
        headers=auth,
        timeout=60,
    )
    assert r_skus.status_code == 200, r_skus.text
    rows = r_skus.json()
    assert isinstance(rows, list) and len(rows) > 0, "no skus returned"

    total_margin = sum(float(r.get("margin_eur") or 0) for r in rows)
    total_revenue = sum(float(r.get("total_revenue_eur") or r.get("revenue_eur") or 0) for r in rows)
    assert total_revenue > 0, "no revenue"
    sku_margin_pct = (total_margin / total_revenue) * 100.0

    r_pnl = requests.get(
        f"{BASE_URL}/api/dashboard/profit-loss",
        params=params,
        headers=auth,
        timeout=60,
    )
    assert r_pnl.status_code == 200, r_pnl.text
    pnl = r_pnl.json()
    # profit-loss returns list of marketplace rows
    if isinstance(pnl, list):
        lm = next((x for x in pnl if x.get("marketplace") == "Leroy Merlin - ES"), None)
        assert lm is not None, f"Leroy Merlin - ES not found in P&L; got {[x.get('marketplace') for x in pnl]}"
        pnl_margin_pct = float(lm["margin_pct"])
    else:
        pnl_margin_pct = float(pnl["margin_pct"])

    diff = abs(sku_margin_pct - pnl_margin_pct)
    print(f"sku_margin_pct={sku_margin_pct:.4f} pnl_margin_pct={pnl_margin_pct:.4f} diff={diff:.4f}")
    assert diff < 0.1, f"Margin parity failed: sku={sku_margin_pct:.4f} vs pnl={pnl_margin_pct:.4f} diff={diff:.4f}"


def test_top_skus_returns_all_needed_columns(auth):
    r = requests.get(
        f"{BASE_URL}/api/dashboard/top-skus",
        params={"date_from": "2025-01-01", "date_to": "2026-12-31", "limit": 5},
        headers=auth,
        timeout=30,
    )
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) > 0
    row = rows[0]
    for k in ["sku", "units", "orders", "revenue_eur", "cogs_eur",
              "operational_eur", "production_shipping_eur", "commission_eur",
              "margin_eur", "margin_pct"]:
        assert k in row, f"missing key {k} in top-skus row: {list(row.keys())}"
