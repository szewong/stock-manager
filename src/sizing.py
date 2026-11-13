"""Real-plan size, guardrails, circuit breaker, sim size, and the gap rule."""

from __future__ import annotations

from dataclasses import dataclass
from math import floor


@dataclass(frozen=True)
class SharePlan:
    shares: int | None
    risk_size: int
    afford_size: int
    planned_risk: float
    note: str | None
    capped: bool


@dataclass(frozen=True)
class GuardrailState:
    open_count: int
    open_risk: float


@dataclass(frozen=True)
class SimSize:
    shares: int
    risk_size: int
    ceiling_size: int
    trimmed: bool


@dataclass(frozen=True)
class GapVerdict:
    binding_max: float
    midpoint: float
    stop_plus: float
    code: str
    sized_shares: int | None
    detail: str


def plan_shares(account: float, risk_pct: float, entry: float, stop: float) -> SharePlan:
    if account <= 0 or risk_pct <= 0 or entry <= 0 or entry <= stop:
        return SharePlan(
            None, 0, 0, 0.0, "size unavailable — entry is not above the stop", False
        )
    budget = account * risk_pct
    risk_size = int(floor(budget / (entry - stop)))
    afford_size = int(floor(account / entry))
    if afford_size <= 0:
        return SharePlan(
            None,
            risk_size,
            afford_size,
            0.0,
            "Affordability: single share exceeds account — paper only",
            False,
        )
    if risk_size <= 0:
        return SharePlan(
            None,
            risk_size,
            afford_size,
            0.0,
            "Risk: one share would risk more than the trade budget — paper only",
            False,
        )
    shares = min(risk_size, afford_size)
    return SharePlan(
        shares,
        risk_size,
        afford_size,
        shares * (entry - stop),
        None,
        shares < risk_size,
    )


def guardrail_note(
    state: GuardrailState,
    new_planned_risk: float,
    *,
    account: float,
    max_positions: int,
    max_total_risk_pct: float,
) -> str | None:
    if state.open_count + 1 > max_positions:
        return "Guardrail — paper only"
    limit = account * max_total_risk_pct
    if state.open_risk + new_planned_risk > limit + 1e-6:
        return "Guardrail — paper only"
    return None


def circuit_breaker_limit(account: float, pct: float = 0.20) -> float:
    return round(account * pct, 2)


def circuit_breaker_tripped(realized_plus_unrealized: float, limit_usd: float) -> bool:
    """`limit_usd` is the positive loss magnitude (20% of account size)."""
    return realized_plus_unrealized <= -abs(limit_usd) + 1e-6


def sim_share_size(
    sim_account: float,
    sim_risk_pct: float,
    ceiling_pct: float,
    entry: float,
    stop: float,
) -> SimSize:
    if entry <= stop or entry <= 0 or sim_account <= 0:
        return SimSize(0, 0, 0, False)
    risk_size = int(floor((sim_account * sim_risk_pct) / (entry - stop)))
    ceiling_size = int(floor((ceiling_pct * sim_account) / entry))
    shares = max(0, min(risk_size, ceiling_size))
    trimmed = risk_size > ceiling_size and shares > 0
    return SimSize(shares, risk_size, ceiling_size, trimmed)


def trim_note(size: SimSize, ceiling_pct: float) -> str:
    pct = int(round(ceiling_pct * 100))
    return (
        f"Sim trimmed to the {pct}% concentration ceiling: {size.shares} shares "
        f"(full risk size {size.risk_size})."
    )


def capital_cap_note(cost: float, available: float) -> str:
    return (
        "Sim skipped — capital cap: cost US$"
        f"{cost:.2f} exceeded available sim cash US${available:.2f} at entry."
    )


def gap_rule(
    price: float,
    stop: float,
    target: float,
    planned_shares: int,
    risk_budget: float,
) -> GapVerdict:
    """Facts of the pre-agreed next-session entry plan. Not an instruction.

    `stop_plus` is the full-size limit (stop + risk budget / planned shares).
    `binding_max` is the hard skip line: the lower of the stop-target midpoint
    and the price at which even one share would use the whole risk budget.
    Between the full-size limit and that skip line the plan's share count is cut.
    """
    midpoint = (stop + target) / 2.0
    if planned_shares <= 0:
        return GapVerdict(midpoint, midpoint, midpoint, "skip", None, "no planned size")
    full_limit = stop + risk_budget / planned_shares
    one_share_limit = stop + risk_budget
    binding = min(midpoint, one_share_limit)
    reasons: list[str] = []
    if price <= stop:
        reasons.append("price is at or below the stop")
    if price > binding + 1e-9:
        reasons.append("price is above the binding maximum")
    if price > stop and (price - stop) > risk_budget + 1e-9:
        reasons.append("one share would risk more than the trade budget")
    if reasons:
        return GapVerdict(binding, midpoint, full_limit, "skip", None, "; ".join(reasons))
    room = price - stop
    fitted = int(floor(risk_budget / room)) if room > 0 else 0
    if fitted <= 0:
        return GapVerdict(
            binding,
            midpoint,
            full_limit,
            "skip",
            None,
            "one share would risk more than the trade budget",
        )
    if fitted < planned_shares:
        return GapVerdict(
            binding,
            midpoint,
            full_limit,
            "reduced",
            fitted,
            f"gap rule would size {fitted} shares at this price",
        )
    return GapVerdict(
        binding,
        midpoint,
        full_limit,
        "full",
        planned_shares,
        "full planned size fits at this price",
    )
