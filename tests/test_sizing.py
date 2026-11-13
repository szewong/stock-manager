"""Real-plan size, guardrails, circuit breaker, sim size, and the gap rule."""

from src.sizing import (
    GuardrailState,
    circuit_breaker_limit,
    circuit_breaker_tripped,
    gap_rule,
    guardrail_note,
    plan_shares,
    sim_share_size,
)


def test_plan_shares_floors_and_caps():
    exact = plan_shares(750, 0.02, 100, 95)
    assert exact.shares == 3
    assert exact.planned_risk == 15
    floored = plan_shares(750, 0.02, 100, 92)
    assert floored.shares == 1
    capped = plan_shares(750, 0.02, 400, 399)
    assert capped.shares == 1
    assert capped.capped
    assert capped.planned_risk == 1
    pricey = plan_shares(750, 0.02, 800, 700)
    assert pricey.shares is None
    assert pricey.note.startswith("Affordability:")
    too_tight = plan_shares(750, 0.02, 100, 80)
    assert too_tight.shares is None
    assert too_tight.note.startswith("Risk:")


def test_guardrail_blocks_count_and_risk_using_capped_plan():
    full = GuardrailState(3, 0)
    assert guardrail_note(full, 15, account=750, max_positions=3, max_total_risk_pct=0.06)
    room = GuardrailState(2, 31)
    assert guardrail_note(room, 15, account=750, max_positions=3, max_total_risk_pct=0.06)
    tight_but_ok = GuardrailState(0, 30)
    assert guardrail_note(tight_but_ok, 15, account=750, max_positions=3, max_total_risk_pct=0.06) is None
    over = GuardrailState(0, 40)
    note = guardrail_note(over, 15, account=750, max_positions=3, max_total_risk_pct=0.06)
    assert note == "Guardrail — paper only"


def test_circuit_breaker_is_twenty_percent_realized_plus_unrealized():
    assert circuit_breaker_limit(750, 0.20) == 150
    assert circuit_breaker_tripped(-150, 150)
    assert circuit_breaker_tripped(-200, 150)
    assert not circuit_breaker_tripped(-149.99, 150)
    assert not circuit_breaker_tripped(0, 150)
    assert not circuit_breaker_tripped(25, 150)


def test_sim_size_trims_to_the_ceiling():
    size = sim_share_size(100_000, 0.02, 0.25, 104, 100)
    assert size.risk_size == 500
    assert size.ceiling_size == 240
    assert size.shares == 240
    assert size.trimmed
    tiny = sim_share_size(100_000, 0.02, 0.25, 100, 99)
    assert tiny.shares == min(tiny.risk_size, tiny.ceiling_size)


def test_gap_rule_binding_price():
    # R = 8, plan shares 1, budget 15. The midpoint is the hard skip line.
    verdict = gap_rule(103, 92, 116, 1, 15)
    assert verdict.code == "full"
    assert abs(verdict.binding_max - 104) < 1e-9
    skipped = gap_rule(105, 92, 116, 1, 15)
    assert skipped.code == "skip"
    under = gap_rule(92, 92, 116, 1, 15)
    assert under.code == "skip"
    # A price above the full-size limit and still under the midpoint cuts the size.
    # stop 95, target 104, midpoint 99.5, full-size limit 98, plan 5, budget 15.
    assert gap_rule(98, 95, 104, 5, 15).code == "full"
    cut = gap_rule(99, 95, 104, 5, 15)
    assert cut.code == "reduced"
    assert cut.sized_shares == 3
    assert gap_rule(100, 95, 104, 5, 15).code == "skip"
    # A lower price never increases the plan.
    assert gap_rule(97, 95, 104, 5, 15).code == "full"
    assert gap_rule(97, 95, 104, 5, 15).sized_shares == 5
