"""NYSE sessions for 2026 and 2027, including observed holidays."""

from datetime import date

from src.calendar_nyse import is_trading_day, nyse_holidays


def test_2026_full_day_closures():
    closed = {
        date(2026, 1, 1),
        date(2026, 1, 19),
        date(2026, 2, 16),
        date(2026, 4, 3),
        date(2026, 5, 25),
        date(2026, 6, 19),
        date(2026, 7, 3),
        date(2026, 9, 7),
        date(2026, 11, 26),
        date(2026, 12, 25),
    }
    assert nyse_holidays(2026) == frozenset(closed)
    assert not is_trading_day(date(2026, 11, 26))
    assert is_trading_day(date(2026, 11, 27))  # early close, still a session
    assert not is_trading_day(date(2026, 11, 21))  # Saturday
    assert is_trading_day(date(2026, 11, 20))


def test_2027_observed_closures():
    holidays = nyse_holidays(2027)
    for day in (
        date(2027, 1, 1),
        date(2027, 1, 18),
        date(2027, 2, 15),
        date(2027, 3, 26),
        date(2027, 5, 31),
        date(2027, 6, 18),
        date(2027, 7, 5),
        date(2027, 9, 6),
        date(2027, 11, 25),
        date(2027, 12, 24),
        date(2027, 12, 31),
    ):
        assert day in holidays
        assert not is_trading_day(day)
