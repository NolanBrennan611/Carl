"""Reminder-system tests R1-R5 (docs/reminder-system.md section 13) plus recurrence edge cases."""

from datetime import UTC, date, datetime, time

import pytest

from carl.domain import recurrence as rec
from carl.domain import timeutil as tu
from carl.domain.errors import ValidationError

CHI = "America/Chicago"


def utc(*args):
    return datetime(*args, tzinfo=UTC)


# ---- R1: reminder times across the November 2026 DST change -------------------------------
def test_r1_us_b1_reminder_instants():
    nine = time(9, 0)
    assert tu.local_to_utc(date(2026, 10, 29), nine, CHI) == utc(2026, 10, 29, 14, 0)  # CDT
    assert tu.local_to_utc(date(2026, 11, 1), nine, CHI) == utc(2026, 11, 1, 15, 0)  # CST


# ---- R2: spring-forward gap (2027-03-14) --------------------------------------------------
def test_r2_nonexistent_local_time_fires_once_after_gap():
    assert tu.local_to_utc(date(2027, 3, 14), time(2, 30), CHI) == utc(2027, 3, 14, 8, 30)


# ---- R3: fall-back overlap (2026-11-01) ---------------------------------------------------
def test_r3_ambiguous_local_time_uses_first_occurrence():
    assert tu.local_to_utc(date(2026, 11, 1), time(1, 30), CHI) == utc(2026, 11, 1, 6, 30)


def test_local_today_uses_household_zone():
    now = utc(2026, 11, 2, 3, 30)  # still Nov 1 in Chicago
    assert tu.local_today(now, CHI) == date(2026, 11, 1)
    assert tu.local_today(now, "Asia/Tokyo") == date(2026, 11, 2)


def test_start_of_local_day():
    assert tu.start_of_local_day_utc(date(2026, 11, 1), CHI) == utc(2026, 11, 1, 5, 0)


def test_db_instant_round_trip_and_ordering():
    dt = datetime(2026, 10, 29, 14, 0, 0, 123000, tzinfo=UTC)
    text = tu.to_db_instant(dt)
    assert text == "2026-10-29T14:00:00.123Z"
    assert tu.from_db_instant(text) == dt
    assert tu.to_db_instant(utc(2026, 1, 1)) < tu.to_db_instant(utc(2026, 1, 2))


def test_naive_datetimes_are_rejected():
    with pytest.raises(ValueError):
        tu.to_db_instant(datetime(2026, 1, 1))


def test_unknown_zone_is_a_validation_error():
    with pytest.raises(ValidationError):
        tu.get_zone("Mars/Olympus")


@pytest.mark.parametrize("bad", ["9am", "24:00", "12:60", "", "9:5"])
def test_parse_hhmm_rejects(bad):
    with pytest.raises(ValidationError):
        tu.parse_hhmm(bad)


def test_parse_hhmm_accepts():
    assert tu.parse_hhmm("08:30") == time(8, 30)


# ---- R4: monthly anchored on the 31st ------------------------------------------------------
def monthly(anchor, **kw):
    return rec.Rule(freq="monthly", interval=1, anchor=anchor, **kw)


def test_r4_month_end_clamps_without_drift():
    rule = monthly(date(2027, 1, 31))
    got = [rec.occurrence(rule, k) for k in range(5)]
    assert got == [
        date(2027, 1, 31),
        date(2027, 2, 28),
        date(2027, 3, 31),
        date(2027, 4, 30),
        date(2027, 5, 31),
    ]


def test_r4_leap_february():
    rule = monthly(date(2028, 1, 31))
    assert rec.occurrence(rule, 1) == date(2028, 2, 29)
    assert rec.occurrence(rule, 2) == date(2028, 3, 31)


def test_monthly_last_day_rule():
    rule = monthly(date(2027, 1, 15), monthday="last")
    assert [rec.occurrence(rule, k) for k in range(3)] == [
        date(2027, 1, 31),
        date(2027, 2, 28),
        date(2027, 3, 31),
    ]


def test_quarterly_via_choice():
    rule = rec.from_choice("quarterly", date(2027, 1, 31))
    assert [rec.occurrence(rule, k) for k in range(3)] == [
        date(2027, 1, 31),
        date(2027, 4, 30),
        date(2027, 7, 31),
    ]


# ---- R5: yearly on Feb 29 ------------------------------------------------------------------
def test_r5_yearly_feb_29():
    rule = rec.Rule(freq="yearly", interval=1, anchor=date(2028, 2, 29))
    assert rec.occurrence(rule, 1) == date(2029, 2, 28)
    assert rec.occurrence(rule, 4) == date(2032, 2, 29)


def test_weekly_biweekly_daily():
    start = date(2026, 11, 2)
    weekly = rec.from_choice("weekly", start)
    biweekly = rec.from_choice("biweekly", start)
    daily = rec.from_choice("daily", start)
    assert rec.occurrence(weekly, 2) == date(2026, 11, 16)
    assert rec.occurrence(biweekly, 2) == date(2026, 11, 30)
    assert rec.occurrence(daily, 10) == date(2026, 11, 12)


def test_repeat_every_multiplies_interval():
    rule = rec.from_choice("weekly", date(2026, 11, 2), repeat_every=3)
    assert rule.interval == 3
    assert rec.occurrence(rule, 1) == date(2026, 11, 23)


def test_repeat_none_means_no_rule_and_bad_values_rejected():
    assert rec.from_choice("none", date(2026, 1, 1)) is None
    with pytest.raises(ValidationError):
        rec.from_choice("hourly", date(2026, 1, 1))
    with pytest.raises(ValidationError):
        rec.from_choice("weekly", date(2026, 1, 1), repeat_every=13)


def test_next_on_or_after_and_after():
    rule = rec.from_choice("weekly", date(2026, 11, 2))
    assert rec.next_on_or_after(rule, date(2026, 11, 2)) == date(2026, 11, 2)
    assert rec.next_on_or_after(rule, date(2026, 11, 3)) == date(2026, 11, 9)
    assert rec.next_after(rule, date(2026, 11, 2)) == date(2026, 11, 9)
    assert rec.next_on_or_after(rule, date(2026, 1, 1)) == date(2026, 11, 2)


def test_us_t4_late_completion_skips_missed_weeks():
    rule = rec.from_choice("weekly", date(2026, 11, 2))
    # Completed on time -> next week. Completed Nov 20 -> first occurrence on/after Nov 20.
    assert rec.next_after(rule, date(2026, 11, 2)) == date(2026, 11, 9)
    assert rec.next_on_or_after(rule, date(2026, 11, 20)) == date(2026, 11, 23)


@pytest.mark.parametrize("choice", list(rec.REPEAT_CHOICES))
def test_next_on_or_after_matches_brute_force(choice):
    rule = rec.from_choice(choice, date(2027, 1, 31))
    all_occ = [rec.occurrence(rule, k) for k in range(2000)]
    for offset in range(0, 900, 17):
        target = date.fromordinal(date(2026, 12, 1).toordinal() + offset)
        expected = next(d for d in all_occ if d >= target)
        assert rec.next_on_or_after(rule, target) == expected


def test_between_inclusive_and_capped():
    rule = rec.from_choice("weekly", date(2026, 11, 2))
    assert rec.between(rule, date(2026, 11, 2), date(2026, 11, 16)) == [
        date(2026, 11, 2),
        date(2026, 11, 9),
        date(2026, 11, 16),
    ]
    assert rec.between(rule, date(2026, 11, 17), date(2026, 11, 8)) == []
    daily = rec.from_choice("daily", date(2026, 1, 1))
    assert len(rec.between(daily, date(2026, 1, 1), date(2030, 1, 1))) == rec.MAX_RESULTS


def test_until_stops_series():
    rule = rec.Rule(freq="weekly", interval=1, anchor=date(2026, 11, 2), until=date(2026, 11, 16))
    assert rec.occurrence(rule, 2) == date(2026, 11, 16)
    assert rec.occurrence(rule, 3) is None
    assert rec.next_after(rule, date(2026, 11, 16)) is None
    assert len(rec.between(rule, date(2026, 1, 1), date(2027, 1, 1))) == 3


def test_json_round_trip_and_validation():
    rule = rec.Rule(
        freq="monthly",
        interval=2,
        anchor=date(2027, 1, 31),
        monthday="last",
        until=date(2030, 1, 1),
    )
    assert rec.parse(rec.to_json(rule)) == rule
    for bad in [
        "not json",
        '{"v":2,"freq":"daily","interval":1,"anchor":"2026-01-01"}',
        '{"v":1,"freq":"hourly","interval":1,"anchor":"2026-01-01"}',
        '{"v":1,"freq":"daily","interval":0,"anchor":"2026-01-01"}',
        '{"v":1,"freq":"daily","interval":1,"anchor":"nope"}',
        '{"v":1,"freq":"weekly","interval":1,"anchor":"2026-01-01","monthday":"last"}',
        '{"freq":"daily"}',
    ]:
        with pytest.raises(ValidationError):
            rec.parse(bad)
