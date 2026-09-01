"""Iteration 13 — loss-makers margin formula sync + dashboard regression.

Modules under test:
  * routes/library.py::loss_makers  (new fields vat_per_unit, vat_pct,
    ship_income_eur, total_revenue_eur, margin_pct + VAT/ship-income math)
  * routes/dashboard.py::top_skus / summary / profit_loss (regression)
  * routes/auth.py::login (playbook checks: bcrypt hash, httpOnly cookie, CORS)
"""
import os
import re
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")

NEW_FIELDS = ["vat_per_unit", "vat_pct", "ship_income_eur", "total_revenue_eur", "margin_pct"]


@pytest.fixture(scope="session")
def creds():
    content = Path("/app/memory/test_credentials.md").read_text(encoding="utf-8")
    emails = re.findall(r"(?im)^\s*[-*]\s*Email:\s*`?([^`\s]+)", content)
    pwds = re.findall(r"(?im)^\s*[-*]\s*Password:\s*`?([^`\s]+)", content)
    if len(emails) < 2 or len(pwds) < 2:
        pytest.skip("credentials not parseable")
    return {"admin": (emails[0], pwds[0]), "user": (emails[1], pwds[1])}


@pytest.fixture(scope="session")
def admin(creds):
    s = requests.Session()
    email, pwd = creds["admin"]
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pwd}, timeout=30)
    if r.status_code != 200:
        pytest.fail(f"admin login failed {r.status_code}: {r.text[:300]}")
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return s


@pytest.fixture(scope="session")
def viewer(creds):
    s = requests.Session()
    email, pwd = creds["user"]
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pwd}, timeout=30)
    if r.status_code != 200:
        pytest.fail(f"user login failed {r.status_code}: {r.text[:300]}")
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return s


# ---------------------------------------------------------------- auth playbook
class TestAuthPlaybook:
    def test_login_returns_token_and_httponly_cookie(self, creds):
        email, pwd = creds["admin"]
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pwd}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert isinstance(body.get("token"), str) and len(body["token"]) > 20
        assert body["user"]["email"] == email
        assert body["user"]["role"] == "admin"
        set_cookie = r.headers.get("set-cookie", "")
        assert "access_token" in set_cookie, f"no access_token cookie: {set_cookie}"
        assert "httponly" in set_cookie.lower(), f"cookie not HttpOnly: {set_cookie}"

    def test_bad_password_401(self, creds):
        email, _ = creds["admin"]
        r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": "definitely-wrong"}, timeout=30)
        assert r.status_code in (401, 429), r.text[:200]

    def test_bcrypt_hash_format(self):
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        env = dotenv_values("/app/backend/.env")

        async def _get():
            c = AsyncIOMotorClient(env["MONGO_URL"])
            u = await c[env["DB_NAME"]].users.find_one({"role": "admin"}, {"_id": 0})
            c.close()
            return u

        u = asyncio.run(_get())
        assert u is not None, "no admin user in DB"
        h = u.get("password_hash") or u.get("hashed_password") or ""
        assert h.startswith("$2b$"), f"hash prefix not $2b$: {h[:7]}"

    def test_cors_allows_credentials_with_explicit_origin(self):
        """Preflight on the public URL is answered by the CDN/ingress (returns
        Allow-Origin: * and no Allow-Credentials), so the app's own CORS layer is
        asserted against the internal port."""
        r = requests.options(
            "http://localhost:8001/api/auth/login",
            headers={
                "Origin": BASE_URL,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
            timeout=30,
        )
        assert r.status_code in (200, 204), r.status_code
        assert r.headers.get("access-control-allow-credentials") == "true"
        origin = r.headers.get("access-control-allow-origin")
        assert origin and origin != "*", f"allow-origin must be explicit, got {origin}"

    def test_brute_force_lockout_after_5_failures(self, creds):
        """Playbook expects lockout/429 after 5 consecutive bad passwords."""
        email, pwd = creds["admin"]
        codes = []
        for _ in range(6):
            r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": "wrong-pass-x"}, timeout=30)
            codes.append(r.status_code)
        # good password must still work if there is no lockout implemented
        ok = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pwd}, timeout=30)
        assert 429 in codes or 423 in codes, f"no lockout after 6 bad attempts, codes={codes} (valid login after: {ok.status_code})"

    def test_unauthenticated_rejected(self):
        r = requests.get(f"{BASE_URL}/api/library/loss-makers", timeout=30)
        assert r.status_code in (401, 403), r.status_code


# ------------------------------------------------------------ loss-makers shape
class TestLossMakers:
    def test_returns_200_list(self, admin):
        r = admin.get(f"{BASE_URL}/api/library/loss-makers", timeout=90)
        assert r.status_code == 200, r.text[:300]
        assert isinstance(r.json(), list)

    def test_new_fields_present_when_rows_exist(self, admin):
        r = admin.get(f"{BASE_URL}/api/library/loss-makers", timeout=90)
        assert r.status_code == 200
        rows = r.json()
        if not rows:
            pytest.skip("no loss-maker rows (empty preview DB)")
        row = rows[0]
        for f in NEW_FIELDS:
            assert f in row, f"missing field {f}"
        assert row["total_revenue_eur"] == pytest.approx(row["revenue_eur"] + row["ship_income_eur"], abs=0.05)
        assert row["net_per_unit"] < 0

    def test_target_margin_param_increases_suggested_price(self, admin):
        r0 = admin.get(f"{BASE_URL}/api/library/loss-makers", params={"target_margin_pct": 0}, timeout=90)
        r30 = admin.get(f"{BASE_URL}/api/library/loss-makers", params={"target_margin_pct": 30}, timeout=90)
        assert r0.status_code == 200 and r30.status_code == 200
        a, b = r0.json(), r30.json()
        if not a or not b:
            pytest.skip("no rows")
        m0 = {(x["sku"], x["marketplace"]): x for x in a}
        for x in b:
            k = (x["sku"], x["marketplace"])
            if k in m0:
                assert x["suggested_price_eur"] >= m0[k]["suggested_price_eur"]
                break

    def test_filters_do_not_error(self, admin):
        for params in (
            {"marketplaces": "TEST_MK"},
            {"date_from": "2026-01-01", "date_to": "2026-12-31"},
            {"stock_only": "true"},
        ):
            r = admin.get(f"{BASE_URL}/api/library/loss-makers", params=params, timeout=90)
            assert r.status_code == 200, f"{params} -> {r.status_code} {r.text[:200]}"
            assert isinstance(r.json(), list)

    def test_no_mongo_object_id_leak(self, admin):
        r = admin.get(f"{BASE_URL}/api/library/loss-makers", timeout=90)
        assert "_id" not in r.text

    def test_readonly_user_can_read(self, viewer):
        r = viewer.get(f"{BASE_URL}/api/library/loss-makers", timeout=90)
        assert r.status_code == 200, r.text[:300]


# ------------------------------------- reconciliation loss-makers vs. top-skus
class TestMarginReconciliation:
    def test_margin_pct_matches_top_skus_for_single_marketplace_sku(self, admin):
        lm = admin.get(f"{BASE_URL}/api/library/loss-makers", timeout=90)
        ts = admin.get(f"{BASE_URL}/api/dashboard/top-skus", params={"limit": 500}, timeout=90)
        assert lm.status_code == 200 and ts.status_code == 200
        lrows, trows = lm.json(), ts.json()
        if not lrows or not trows:
            pytest.skip("no data to reconcile")
        tmap = {t["sku"]: t for t in trows}
        # only SKUs that appear exactly once in loss-makers (single marketplace)
        seen = {}
        for r in lrows:
            seen.setdefault(r["sku"], []).append(r)
        checked = 0
        mismatches = []
        for sku, rs in seen.items():
            if len(rs) != 1 or sku not in tmap:
                continue
            t = tmap[sku]
            if t["units"] != rs[0]["units"]:
                continue  # different line filters (unit_price>0) — not comparable
            expected = t["margin_pct"]
            got = rs[0]["margin_pct"]
            checked += 1
            if abs(expected - got) > 1.0:
                mismatches.append((sku, expected, got))
        if checked == 0:
            pytest.skip("no comparable single-marketplace SKU")
        assert not mismatches, f"margin_pct mismatch vs top-skus: {mismatches[:5]}"


# -------------------------------------------------------- dashboard regression
class TestDashboardRegression:
    def test_summary(self, admin):
        r = admin.get(f"{BASE_URL}/api/dashboard/summary", timeout=90)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        for k in ("revenue_eur", "orders", "units"):
            assert k in d, f"summary missing {k}: {list(d)[:15]}"

    def test_top_skus(self, admin):
        r = admin.get(f"{BASE_URL}/api/dashboard/top-skus", params={"limit": 10}, timeout=90)
        assert r.status_code == 200, r.text[:300]
        rows = r.json()
        assert isinstance(rows, list)
        if rows:
            for k in ("sku", "units", "revenue_eur", "vat_eur", "cogs_eur", "margin_eur", "margin_pct", "has_cost"):
                assert k in rows[0], f"top-skus missing {k}"

    def test_profit_loss(self, admin):
        r = admin.get(f"{BASE_URL}/api/dashboard/profit-loss", timeout=90)
        assert r.status_code == 200, r.text[:300]
        assert isinstance(r.json(), (list, dict))

    def test_library_skus(self, admin):
        r = admin.get(f"{BASE_URL}/api/library/skus", params={"limit": 20}, timeout=120)
        assert r.status_code == 200, r.text[:300]
        assert isinstance(r.json(), list)
