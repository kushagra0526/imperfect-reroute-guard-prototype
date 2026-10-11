import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reroute import guard, signals  # noqa: E402
from reroute.metrics import score  # noqa: E402
from reroute.plan import Session, fifty_k_plan  # noqa: E402
from reroute.scenarios import ALL, check, play  # noqa: E402
from reroute.season import season  # noqa: E402


@pytest.mark.parametrize("make", ALL, ids=lambda f: f.__name__)
def test_scripted_days_match_written_expectations(make):
    sc = make()
    assert check(sc, play(sc)) == []


def _raw():
    return {"activities": [], "sleep": [], "hrv": [], "checkins": {}, "aqi": {}}


def test_same_run_from_three_sources_counts_once():
    t = datetime(2027, 1, 5, 13, 0)
    raw = _raw()
    raw["activities"] = [
        {"source": "garmin", "sport": "run", "start_utc": t, "minutes": 60, "avg_hr": 150, "tz_min": -360},
        {"source": "strava", "sport": "run", "start_utc": t + timedelta(seconds=40), "minutes": 61, "avg_hr": 150, "tz_min": -360},
        {"source": "apple", "sport": "run", "start_utc": t, "minutes": 60, "avg_hr": None, "tz_min": -360},
    ]
    c, n = signals.clean(raw, 185), signals.naive(raw, 185)
    assert len(c["activities"]) == 1 and c["activities"][0]["source"] == "garmin"
    assert c["activities"][0]["sources"] == ["apple", "garmin", "strava"]
    assert sum(n["load"].values()) > 2.5 * sum(c["load"].values())


def test_hrv_baseline_does_not_mix_rmssd_and_sdnn():
    raw = _raw()
    t0 = datetime(2027, 1, 1, 12, 30)
    for k in range(14):
        raw["hrv"].append({"source": "garmin", "metric": "rmssd", "value": 55 + (k % 3), "end_utc": t0 + timedelta(days=k), "tz_min": -360})
    raw["hrv"].append({"source": "apple", "metric": "sdnn", "value": 80, "end_utc": t0 + timedelta(days=14), "tz_min": -360})
    d = (t0 + timedelta(days=14) - timedelta(minutes=360)).date()
    assert signals.clean(raw, 185)["hrv"][d]["z"] is None          # rebuilding a SDNN baseline
    assert signals.naive(raw, 185)["hrv"][d]["z"] > 10              # "huge recovery"


def test_sleep_is_dated_by_local_wake_up_and_missing_is_unknown():
    raw = _raw()
    end = datetime(2027, 1, 4, 21, 30)                              # 06:30 on Jan 5 in Tokyo
    raw["sleep"].append({"source": "garmin", "start_utc": end - timedelta(hours=7.5), "end_utc": end, "tz_min": 540})
    c, n = signals.clean(raw, 185), signals.naive(raw, 185)
    assert c["sleep"][date(2027, 1, 5)] == pytest.approx(7.5)
    assert n["sleep"].get(date(2027, 1, 5)) == 0.0                  # the naive bug
    assert c["sleep"].get(date(2027, 1, 6)) is None                 # no data is not zero


def test_guard_blocks_fever_and_never_allows_back_to_back_keys():
    d = date(2027, 2, 2)
    sig = {"checkins": {d: {"symptoms": {"fever"}}}, "sleep": {}, "hrv": {}, "offset": {}, "load": {}, "aqi": {}}
    v, r, s = guard.check(Session("tempo", 50), d, sig, {})
    assert v == "BLOCK" and s.kind == "rest"
    sig["checkins"] = {}
    v, r, s = guard.check(Session("tempo", 50), d, sig, {d - timedelta(days=1): Session("intervals", 60)})
    assert "KEY_SPACING" in {c for c, _ in r} and not s.key


def test_seasons_reroute_has_no_unsafe_days_and_keeps_most_fitness():
    out, life, plan = season(3)
    race = max(plan)
    rr = score(life, out["reroute"][1], race, plan)
    st = score(life, out["static plan"][1], race, plan)
    for k in ("sick_hard", "return_too_fast", "jetlag_key", "short_sleep_key", "back_to_back_keys"):
        assert rr[k] == 0, k
    assert st["sick_hard"] > 0
    assert rr["fitness_ctl"] > 0.8 * st["fitness_ctl"]


def test_plan_ends_with_race_and_long_runs_build():
    plan = fifty_k_plan(date(2027, 4, 10))
    longs = [s.minutes for s in plan.values() if s.kind == "long"]
    assert plan[date(2027, 4, 10)].kind == "race" and max(longs) >= 150 and longs[0] < 100
