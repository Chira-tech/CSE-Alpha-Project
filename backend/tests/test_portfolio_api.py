"""POST /portfolio/upload, GET /portfolio/holdings, GET /portfolio/
snapshots — API-layer wiring for the real portfolio-import feature.
Builds a genuine small `.xlsx` file with openpyxl and uploads real bytes
through the real endpoint, rather than mocking the parse step — the
same "exercise the real boundary" discipline every other file-upload-
shaped test in this system already applies to PDFs.
"""
from __future__ import annotations

import io

from app.models.securities import Security

HEADER = [
    "Security", "Quantity", "Cleared Balance", "Available Balance",
    "Unsettled Buy", "Unsettled Sell", "Holding % (Quantity)", "Avg Price",
    "B.E.S Price", "Total Cost", "Traded Price", "Market Value",
    "Holding % (Market Value)", "Sales Commission", "Sales Proceeds",
    "Unrealized Gain / (Loss)", "Unrealized Gain/Loss %", "Unr Today Gain/(Loss)",
]


def _build_real_xlsx_bytes() -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio"
    ws.append(["Portfolio (TEST ACCOUNT) - EQUITY"])
    ws.append([])
    ws.append(HEADER)
    ws.append([
        "JKH.N0000", 1000.0, 1000.0, 1000.0, 0.0, 0.0, 28.47, 20.224, 20.45,
        20224.0, 20.0, 20000.0, 26.06, 224.0, 19776.0, -448.0, -2.22, 0.0,
    ])
    ws.append([
        "CBNK.N0000", 1000.0, 1000.0, 1000.0, 0.0, 0.0, 28.47, 8.0896, 8.18,
        8089.6, 7.5, 7500.0, 9.77, 84.0, 7416.0, -673.6, -8.33, 0.0,
    ])
    ws.append([
        "Total", None, None, None, None, None, None, None, None,
        28313.6, None, 27500.0, None, 308.0, 27192.0, -1121.6, None, 0.0,
    ])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_upload_a_real_xlsx_file(client):
    xlsx_bytes = _build_real_xlsx_bytes()
    r = client.post(
        "/portfolio/upload",
        files={"file": ("Portfolio.xlsx", xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["positions"]) == 2
    assert body["identity_check_passed"] is True
    assert body["source_filename"] == "Portfolio.xlsx"


def test_upload_rejects_a_file_with_no_recognisable_header(client):
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["not", "a", "real", "portfolio", "export"])
    buf = io.BytesIO()
    wb.save(buf)

    r = client.post(
        "/portfolio/upload",
        files={"file": ("not_a_portfolio.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 422


def test_upload_rejects_a_file_that_is_not_a_real_xlsx(client):
    r = client.post(
        "/portfolio/upload",
        files={"file": ("fake.xlsx", b"this is not a real xlsx file", "application/octet-stream")},
    )
    assert r.status_code == 400


def test_holdings_is_none_before_any_upload(client):
    r = client.get("/portfolio/holdings")
    assert r.status_code == 200
    assert r.json() is None


def test_holdings_reflects_the_most_recent_upload(client, db_session):
    db_session.add(Security(ticker="JKH.N0000", name="John Keells Holdings"))
    db_session.commit()

    client.post(
        "/portfolio/upload",
        files={"file": ("Portfolio.xlsx", _build_real_xlsx_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    r = client.get("/portfolio/holdings")
    assert r.status_code == 200
    body = r.json()
    assert body is not None
    assert {p["ticker"] for p in body["positions"]} == {"JKH.N0000", "CBNK.N0000"}
    # CBNK.N0000 has no real Security row seeded above — named, not silently dropped.
    assert body["unrecognized_tickers"] == ["CBNK.N0000"]


def test_snapshots_list_grows_with_each_upload(client):
    xlsx_bytes = _build_real_xlsx_bytes()
    client.post("/portfolio/upload", files={"file": ("first.xlsx", xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    client.post("/portfolio/upload", files={"file": ("second.xlsx", xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    r = client.get("/portfolio/snapshots")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert {s["source_filename"] for s in body} == {"first.xlsx", "second.xlsx"}
