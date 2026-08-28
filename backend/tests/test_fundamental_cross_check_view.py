import datetime as dt
from decimal import Decimal

from app.domain.fundamental_cross_check_view import (
    ai_assisted_filing_groups,
    gather_filing_facts,
    load_rows_by_ticker,
)
from app.models.enums import ProvenanceTier
from app.models.fundamentals import Fundamental
from app.models.securities import Security


def _sec(db, ticker):
    db.add(Security(ticker=ticker, name=ticker))


def _fund(db, **kw):
    defaults = dict(
        ticker="AAA.N0000",
        period_end=dt.date(2024, 3, 31),
        period_type="annual",
        first_available_date=dt.date(2024, 6, 1),
        version=1,
        statement_line="total_assets",
        value=Decimal("1000"),
        currency="LKR",
        provenance_tier=ProvenanceTier.AI_ASSISTED,
        restated_flag=False,
        source_url="http://x/aaa-2024-annual.pdf",
        source_page=1,
        source_snippet="",
        confirmed_by=None,
        confirmed_at=None,
    )
    defaults.update(kw)
    db.add(Fundamental(**defaults))


def test_only_periods_with_a_pending_row_become_groups(db_session):
    _sec(db_session, "AAA.N0000")
    _fund(db_session, statement_line="total_assets", value=Decimal("100"))
    _fund(
        db_session,
        period_end=dt.date(2023, 3, 31),
        statement_line="total_assets",
        value=Decimal("90"),
        provenance_tier=ProvenanceTier.REPORTED,
        confirmed_by="human",
        source_url="http://x/aaa-2023-annual.pdf",
    )
    db_session.commit()

    groups = ai_assisted_filing_groups(load_rows_by_ticker(db_session))
    assert [(g.ticker, g.period_end.isoformat()) for g in groups] == [("AAA.N0000", "2024-03-31")]


def test_cross_source_only_counts_a_different_source_url(db_session):
    _sec(db_session, "AAA.N0000")
    # the pending row
    _fund(db_session, statement_line="inventories", value=Decimal("500"))
    # a later filing's comparative column for the SAME period_end, different URL
    _fund(
        db_session,
        statement_line="inventories",
        value=Decimal("500"),
        period_type="quarterly",
        source_url="http://x/aaa-2024-q1.pdf",
        provenance_tier=ProvenanceTier.REPORTED,
        confirmed_by="human",
    )
    # a same-URL sibling must NOT count as cross-source
    _fund(db_session, statement_line="trade_payables", value=Decimal("400"))
    db_session.commit()

    by_ticker = load_rows_by_ticker(db_session)
    group = ai_assisted_filing_groups(by_ticker)[0]
    facts = gather_filing_facts(group, by_ticker, reextracted_values=None)
    assert facts.cross_source_values.get("inventories") == [Decimal("500")]
    assert "trade_payables" not in facts.cross_source_values


def test_dual_listing_counterpart_is_paired_and_its_values_gathered(db_session):
    _sec(db_session, "BBB.N0000")
    _sec(db_session, "BBB.X0000")
    _fund(db_session, ticker="BBB.N0000", statement_line="total_equity", value=Decimal("777"),
          source_url="http://x/bbb-n.pdf")
    _fund(db_session, ticker="BBB.X0000", statement_line="total_equity", value=Decimal("777"),
          source_url="http://x/bbb-x.pdf", provenance_tier=ProvenanceTier.REPORTED, confirmed_by="human")
    db_session.commit()

    by_ticker = load_rows_by_ticker(db_session, {"BBB.N0000", "BBB.X0000"})
    group = next(g for g in ai_assisted_filing_groups(by_ticker) if g.ticker == "BBB.N0000")
    facts = gather_filing_facts(group, by_ticker, reextracted_values=None)
    assert facts.dual_listing_values.get("total_equity") == Decimal("777")


def test_quarterly_window_collects_four_quarters_for_an_annual_filing(db_session):
    _sec(db_session, "CCC.N0000")
    _fund(db_session, ticker="CCC.N0000", statement_line="revenue", value=Decimal("400"),
          source_url="http://x/ccc-annual.pdf")
    for i, q_end in enumerate(
        [dt.date(2023, 6, 30), dt.date(2023, 9, 30), dt.date(2023, 12, 31), dt.date(2024, 3, 31)]
    ):
        _fund(
            db_session,
            ticker="CCC.N0000",
            period_end=q_end,
            period_type="quarterly",
            statement_line="revenue",
            value=Decimal("100"),
            source_url=f"http://x/ccc-q{i}.pdf",
            provenance_tier=ProvenanceTier.REPORTED,
            confirmed_by="human",
        )
    # a stale quarter well outside the fiscal year must be ignored
    _fund(
        db_session,
        ticker="CCC.N0000",
        period_end=dt.date(2022, 3, 31),
        period_type="quarterly",
        statement_line="revenue",
        value=Decimal("9999"),
        source_url="http://x/ccc-old.pdf",
        provenance_tier=ProvenanceTier.REPORTED,
        confirmed_by="human",
    )
    db_session.commit()

    by_ticker = load_rows_by_ticker(db_session)
    group = next(g for g in ai_assisted_filing_groups(by_ticker) if g.period_type == "annual")
    facts = gather_filing_facts(group, by_ticker, reextracted_values=None)
    assert facts.quarterly_period_count == 4
    assert sorted(facts.quarterly_values["revenue"]) == [Decimal("100")] * 4


def test_filing_failure_marker_is_detected(db_session):
    _sec(db_session, "DDD.N0000")
    _fund(db_session, ticker="DDD.N0000", statement_line="total_assets", value=Decimal("5"),
          source_snippet="EXTRACTION FAILED ARITHMETIC CHECK - assets = equity + liabilities")
    db_session.commit()
    by_ticker = load_rows_by_ticker(db_session)
    facts = gather_filing_facts(ai_assisted_filing_groups(by_ticker)[0], by_ticker, None)
    assert facts.has_filing_failure_marker is True
