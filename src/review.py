"""Weekly membership review. Proposals only; the watchlist is not changed."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from src.report import render_review, sector_order
from src.schema import SECTORS
from src.state import load_papers, load_settings, load_watch


def run_review(root: Path, today: date) -> str:
    settings = load_settings(root)
    if not settings.get("weekly_watchlist_review"):
        return "Weekly watchlist review is turned off in settings. Nothing was proposed.\n"
    watch = load_watch(root)
    papers = load_papers(root)
    open_names = {pos.ticker for pos in papers if pos.status in ("Open", "Half sold")}
    known = {name.lower() for name in SECTORS}
    grouped = {name: [] for name in SECTORS}
    other = []
    for row in watch:
        if row.theme in grouped:
            grouped[row.theme].append(row)
        elif row.theme.lower() in known:
            canonical = next(name for name in SECTORS if name.lower() == row.theme.lower())
            grouped[canonical].append(row)
        else:
            other.append(row)

    sections: list[str] = []
    for sector in sector_order():
        members = grouped[sector]
        lines = [f"## {sector}", ""]
        if not members:
            lines.append(
                "No names on the list. No removal proposals. "
                "New names are not proposed here; this program does not fetch an unverified universe."
            )
        else:
            lines.append("Members: " + ", ".join(row.ticker for row in members) + ".")
            proposals = []
            held = []
            for row in members:
                if row.last_price is None or row.ma50 in (None, 0) or row.consol_high is None:
                    continue
                damaged = row.last_price < row.ma50 * 0.85 and row.consol_high < row.ma50
                if not damaged:
                    continue
                if row.ticker in open_names:
                    held.append(row)
                    continue
                gap = (row.ma50 - row.last_price) / row.ma50 * 100.0
                proposals.append(
                    f"{row.ticker} last {row.last_price:.2f} is {gap:.1f}% under MA50 {row.ma50:.2f}, "
                    f"and the 15-session high {row.consol_high:.2f} is still under MA50."
                )
            if proposals:
                lines.append("Removal proposals (structural — deep technical damage, not one bad week):")
                lines.extend(f"- {line}" for line in proposals)
            else:
                lines.append("Removal proposals: none.")
            for row in held:
                lines.append(
                    f"{row.ticker} is far under MA50 and has an open paper position, so no removal is proposed."
                )
            lines.append(
                "New names are not proposed here; this program does not fetch an unverified universe."
            )
        lines.append("")
        sections.extend(lines)
    if other:
        sections.append("## Themes outside the ten sectors")
        sections.append("")
        sections.append("Members: " + ", ".join(f"{row.ticker} ({row.theme})" for row in other) + ".")
        sections.append("No removal is proposed from an unrecognized theme without a stored price check.")
        sections.append("")
    sections.append(
        "Nothing was written to the watchlist or the deferred bench. "
        "A name moves only when it is picked explicitly."
    )
    return render_review(today, sections)
