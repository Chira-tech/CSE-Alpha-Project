"""
`app.domain.composite_ranking_snapshot_view` — the canonical
`CompositeRankingView` serialization, snapshot persistence, and the
cross-snapshot reads (week-over-week insights, per-row score series) that
back the redesigned Opportunities screen.

Builds `CompositeRankingView` objects directly rather than running the
real ~70s universe pass — this file is about the freeze/diff logic, not
the scoring, which `test_composite_ranking_view.py` already covers.
"""
from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal

from app.domain.composite_ranking_snapshot_view import (
    build_insights,
    latest_snapshot,
    score_series_by_ticker,
    recent_snapshots,
    serialize_ranking,
    snapshot_on_or_before,
    write_snapshot,
)
from app.domain.composite_ranking_view import CompositeRankingView, RankedComposite
from app.domain.composite_score_view import UNEVALUABLE_INTEGRITY
from app.domain.composite_score import PILLAR_SPECS


def _pillars(included_score=Decimal("70"), n_included=7):
    from app.domain.composite_score_view import PillarScore

    out = []
    for i, spec in enumerate(PILLAR_SPECS):
        inc = i < n_included
        out.append(
            PillarScore(
                spec.key, spec.label, spec.weight_pct,
                included_score if inc else None, inc,
                None if inc else "not computable for this ticker",
            )
        )
    return tuple(out)


def _row(ticker, *, score, verdict="Buy", sector="Banks", pillars_included=7, confidence="high"):
    return RankedComposite(
        ticker=ticker,
        name=f"{ticker} Ltd",
        archetype="bank",
        cse_sector=sector,
        verdict=verdict,
        decision_confidence=confidence,
        total_score=None if score is None else Decimal(str(score)),
        pillars=_pillars(n_included=pillars_included),
        pillars_included=pillars_included,
        weight_covered_pct=Decimal("100"),
        weight_used_pct={},
        integrity=UNEVALUABLE_INTEGRITY,
        blended_fair_value_per_share=Decimal("100"),
        current_price=Decimal("80"),
        discount_to_fair_value_pct=Decimal("0.2"),
        valuation_pillar_percentile=Decimal("65"),
        warnings=(),
    )


def _view(as_of, rows):
    return CompositeRankingView(as_of=as_of, ranked=tuple(rows), excluded=())


def test_serialize_ranking_round_trips_through_json_and_the_response_model():
    from app.api.routes.composite_ranking import CompositeRankingOut

    view = _view(dt.date(2026, 8, 30), [_row("AAA.N0000", score=88), _row("BBB.N0000", score=71)])
    body = serialize_ranking(view)
    reloaded = json.loads(json.dumps(body))

    assert reloaded["as_of"] == "2026-08-30"
    assert [r["ticker"] for r in reloaded["ranked"]] == ["AAA.N0000", "BBB.N0000"]
    row = reloaded["ranked"][0]
    assert row["verdict"] == "Buy"
    assert row["cse_sector"] == "Banks"
    assert row["total_score"] == "88"
    assert {p["key"] for p in row["pillars"]} == {s.key for s in PILLAR_SPECS}

    # The API's own response model must accept this dict unchanged (plus
    # the read-time fields the route layers on).
    reloaded.update(computed_at=None, is_stale=False, snapshot_available=True, insights=[])
    for r in reloaded["ranked"]:
        r["score_series"] = []
    CompositeRankingOut.model_validate(reloaded)


def test_write_and_latest_snapshot(db_session):
    v1 = _view(dt.date(2026, 8, 28), [_row("AAA.N0000", score=50)])
    v2 = _view(dt.date(2026, 8, 30), [_row("AAA.N0000", score=60)])

    write_snapshot(db_session, v1, computed_at=dt.datetime(2026, 8, 28, 11, tzinfo=dt.timezone.utc), duration_seconds=Decimal("70.1"))
    write_snapshot(db_session, v2, computed_at=dt.datetime(2026, 8, 30, 11, tzinfo=dt.timezone.utc), duration_seconds=Decimal("69.4"))

    newest = latest_snapshot(db_session)
    assert newest.as_of == dt.date(2026, 8, 30)
    assert newest.ranked_count == 1
    assert json.loads(newest.payload)["ranked"][0]["total_score"] == "60"
    assert len(recent_snapshots(db_session)) == 2


def test_snapshot_on_or_before_picks_the_newest_old_enough_one(db_session):
    for d in (dt.date(2026, 8, 10), dt.date(2026, 8, 20), dt.date(2026, 8, 30)):
        write_snapshot(
            db_session, _view(d, [_row("AAA.N0000", score=50)]),
            computed_at=dt.datetime(d.year, d.month, d.day, 11, tzinfo=dt.timezone.utc),
            duration_seconds=Decimal("70"),
        )
    picked = snapshot_on_or_before(db_session, dt.date(2026, 8, 23))
    assert picked.as_of == dt.date(2026, 8, 20)
    assert snapshot_on_or_before(db_session, dt.date(2026, 8, 1)) is None


def test_build_insights_returns_nothing_without_a_prior_snapshot():
    latest = serialize_ranking(_view(dt.date(2026, 8, 30), [_row("AAA.N0000", score=80)]))
    assert build_insights(latest, None) == []


def test_build_insights_reports_verdict_moves_score_moves_and_sector_shifts():
    prior = serialize_ranking(
        _view(
            dt.date(2026, 8, 23),
            [
                _row("UP.N0000", score=60, verdict="Hold", sector="Banks"),
                _row("DOWN.N0000", score=80, verdict="Buy", sector="Banks"),
                _row("THIN.N0000", score=40, verdict="Hold", sector="Diversified", pillars_included=2),
            ],
        )
    )
    latest = serialize_ranking(
        _view(
            dt.date(2026, 8, 30),
            [
                _row("UP.N0000", score=75, verdict="Buy", sector="Banks"),      # +15, verdict up
                _row("DOWN.N0000", score=79, verdict="Hold", sector="Banks"),   # verdict softened
                _row("THIN.N0000", score=70, verdict="Buy", sector="Diversified", pillars_included=2),  # thin — no score headline
            ],
        )
    )
    insights = build_insights(latest, prior)
    blob = " | ".join(insights)

    assert "UP.N0000" in blob and "Hold→Buy" in blob
    assert "DOWN.N0000" in blob and "Buy→Hold" in blob
    assert "UP.N0000 composite +15" in blob
    assert "THIN.N0000 composite" not in blob  # 2-pillar row never headlines a score move
    assert "Banks sector average" in blob


def test_build_insights_ignores_transitions_in_and_out_of_no_call_states():
    """Gaining or losing coverage for a name (Insufficient data / Withheld
    ↔ a real verdict) is not a decision changing — it belongs to the
    trust bar, not the decisions list — so it never appears here, however
    many names move at once."""
    prior = serialize_ranking(
        _view(
            dt.date(2026, 8, 23),
            [
                _row("NEWCOV.N0000", score=55, verdict="Insufficient data"),
                _row("LOSTCOV.N0000", score=55, verdict="Sell"),
                _row("REAL.N0000", score=60, verdict="Hold"),
            ],
        )
    )
    latest = serialize_ranking(
        _view(
            dt.date(2026, 8, 30),
            [
                _row("NEWCOV.N0000", score=55, verdict="Sell"),      # coverage gained — ignored
                _row("LOSTCOV.N0000", score=55, verdict="Withheld"),  # coverage lost — ignored
                _row("REAL.N0000", score=60, verdict="Trim"),         # real re-rate — reported
            ],
        )
    )
    blob = " | ".join(build_insights(latest, prior))
    assert "NEWCOV" not in blob and "LOSTCOV" not in blob
    assert "REAL.N0000" in blob and "Hold→Trim" in blob


def test_verdict_transition_sentence_caps_the_name_list():
    prior = serialize_ranking(
        _view(dt.date(2026, 8, 23), [_row(f"T{i:03d}.N0000", score=50, verdict="Hold") for i in range(20)])
    )
    latest = serialize_ranking(
        _view(dt.date(2026, 8, 30), [_row(f"T{i:03d}.N0000", score=50, verdict="Sell") for i in range(20)])
    )
    (sentence,) = [s for s in build_insights(latest, prior) if "Verdict softened" in s]
    assert "and 10 more" in sentence
    assert sentence.count("→") == 10


def test_score_series_by_ticker_is_oldest_first_and_skips_unranked_runs(db_session):
    write_snapshot(
        db_session, _view(dt.date(2026, 8, 20), [_row("AAA.N0000", score=55)]),
        computed_at=dt.datetime(2026, 8, 20, 11, tzinfo=dt.timezone.utc), duration_seconds=Decimal("70"),
    )
    write_snapshot(
        db_session, _view(dt.date(2026, 8, 30), [_row("AAA.N0000", score=None), _row("BBB.N0000", score=90)]),
        computed_at=dt.datetime(2026, 8, 30, 11, tzinfo=dt.timezone.utc), duration_seconds=Decimal("70"),
    )
    series = score_series_by_ticker(recent_snapshots(db_session))

    assert [p["total_score"] for p in series["AAA.N0000"]] == ["55"]  # the None run contributes no point
    assert series["BBB.N0000"] == [{"as_of": "2026-08-30", "total_score": "90"}]
