"""Scripted days. The expected answer for each was written down before running it.

Each scenario lives a full plan up to the target day so baselines and load history are real.
"""
from datetime import date, timedelta

from .coach import CatchUp, Rerouter, Static
from .plan import fifty_k_plan
from .season import Life, run

RACE = date(2027, 4, 10)
PLAN = fifty_k_plan(RACE)
START = min(PLAN)


def _dow(week, weekday):
    """Date in build week `week` (0-based, after the 4 base weeks) on weekday (Mon=0)."""
    return START + timedelta(days=7 * (4 + week) + weekday)


def founder_morning():
    d = _dow(6, 5)                                    # a Saturday long run, 115 min ("nearly two hours")
    L = Life(home_tz=-360)
    for k in range(1, 11):                            # ten days in Florence; flew home yesterday
        L.tz[d - timedelta(days=k)] = 120
    L.busy.add(d - timedelta(days=1))                 # travel day
    L.sleep[d] = 4.6
    L.symptoms[d] = {"sore throat", "congestion"}
    return {"id": "founder-morning", "title": "Florence → Mexico City, 4.6 h sleep, sore throat",
            "life": L, "day": d, "followup": d + timedelta(days=1),
            "expect": {"reroute": {"not_key": True, "max_min": 30, "codes": {"SICK_ABOVE_NECK", "JET_LAG", "SHORT_SLEEP"},
                                   "moved_to": d + timedelta(days=1)},
                       "followup": {"kind": "long"}}}


def device_switch():
    d = _dow(9, 1)                                    # Tuesday intervals
    L = Life(); L.switch_to_apple = d - timedelta(days=3)
    return {"id": "device-switch", "title": "Garmin → Apple Watch 3 days ago (RMSSD → SDNN)",
            "life": L, "day": d, "expect": {"reroute": {"same_as_plan": True},
                                             "catch-up coach": {"codes": {"GREEN_LIGHT"}}}}


def triple_sync():
    d = _dow(8, 3)                                    # Thursday tempo
    L = Life(); L.strava_from = d - timedelta(days=12); L.apple_mirror_from = d - timedelta(days=12)
    return {"id": "triple-sync", "title": "Every run arrives from Garmin, Strava and Apple Health",
            "life": L, "day": d, "expect": {"reroute": {"same_as_plan": True},
                                             "catch-up coach": {"codes": {"OVERREACHING"}}}}


def watch_off():
    d = _dow(6, 5)
    L = Life(); L.watch_off.add(d)
    return {"id": "watch-off", "title": "Watch on the charger last night (no sleep data)",
            "life": L, "day": d, "expect": {"reroute": {"same_as_plan": True},
                                             "catch-up coach": {"codes": {"SLEEP_DEBT"}}}}


def tokyo():
    d = _dow(5, 1)
    L = Life(home_tz=540)
    return {"id": "tokyo", "title": "Athlete in Tokyo (UTC+9): sleep dated by UTC lands on the wrong day",
            "life": L, "day": d, "expect": {"reroute": {"same_as_plan": True},
                                             "catch-up coach": {"codes": {"SLEEP_DEBT"}}}}


def missed_week():
    d = _dow(10, 5)
    L = Life()
    for k in range(1, 6):
        L.busy.add(d - timedelta(days=k))
    return {"id": "missed-week", "title": "Work trip at home: Mon–Fri missed, Saturday long run",
            "life": L, "day": d, "expect": {"reroute": {"kind": "long", "no_make_up": True},
                                             "catch-up coach": {"codes": {"MAKE_UP"}}}}


def after_fever():
    d = _dow(9, 1)
    L = Life()
    for k in range(1, 4):
        L.symptoms[d - timedelta(days=k)] = {"fever", "body aches"}
    return {"id": "after-fever", "title": "Fever Sat–Mon, symptom-free this morning, intervals planned",
            "life": L, "day": d, "expect": {"reroute": {"not_key": True, "codes": {"RETURN_AFTER_ILLNESS"}}}}


def bad_nights():
    d = _dow(9, 3)
    L = Life()
    for k in (0, 1):
        L.sleep[d - timedelta(days=k)] = 4.8; L.hrv_drop[d - timedelta(days=k)] = 0.35
    return {"id": "bad-nights", "title": "Two genuinely bad nights: 4.8 h, HRV down",
            "life": L, "day": d, "expect": {"reroute": {"not_key": True, "codes": {"SHORT_SLEEP", "LOW_HRV"}}}}


def normal_day():
    d = _dow(11, 5)
    return {"id": "normal-day", "title": "Nothing wrong: do the long run",
            "life": Life(), "day": d, "expect": {"reroute": {"same_as_plan": True},
                                                  "catch-up coach": {"same_as_plan": True}}}


def bad_air():
    d = _dow(7, 1)
    L = Life(); L.aqi[d] = 185
    return {"id": "bad-air", "title": "AQI 185 (wildfire smoke)",
            "life": L, "day": d, "expect": {"reroute": {"kind": "intervals", "indoor": True, "codes": {"AIR_QUALITY"}}}}


ALL = [founder_morning, device_switch, triple_sync, watch_off, tokyo, missed_week, after_fever,
       bad_nights, normal_day, bad_air]


def play(sc, seed=7):
    """Run every coach up to the scenario day (and the follow-up day). Returns decisions per coach."""
    end = sc.get("followup") or sc["day"]
    out = {}
    for name, mk, pipe in [("static plan", lambda: Static(PLAN), "clean"),
                           ("catch-up coach", lambda: CatchUp(PLAN), "naive"),
                           ("reroute", lambda: Rerouter(PLAN, RACE), "clean")]:
        dec, ex, raw = run(sc["life"], PLAN, RACE, mk(), START, end, seed=seed, pipeline=pipe)
        by = {x.date: x for x in dec if x}
        out[name] = {"day": by.get(sc["day"]), "followup": by.get(sc.get("followup")), "executed": ex}
    return out


def check(sc, res):
    """Compare with the written expectations. Returns a list of failures (empty = pass)."""
    fails = []
    planned = PLAN[sc["day"]]
    for who, exp in sc["expect"].items():
        if who == "followup":
            dec = res["reroute"]["followup"]
        else:
            dec = res[who]["day"]
        s = dec.session if dec else None
        codes = {c for c, _ in dec.reasons} if dec else set()
        if exp.get("same_as_plan") and (s.kind, s.minutes) != (planned.kind, planned.minutes):
            fails.append(f"{who}: expected the plan ({planned.label()}), got {s.label()} {sorted(codes)}")
        if exp.get("not_key") and s.key:
            fails.append(f"{who}: expected no key session, got {s.label()}")
        if "max_min" in exp and s.minutes > exp["max_min"]:
            fails.append(f"{who}: expected at most {exp['max_min']} min, got {s.minutes}")
        if "kind" in exp and s.kind != exp["kind"]:
            fails.append(f"{who}: expected {exp['kind']}, got {s.label()}")
        if exp.get("indoor") and not s.indoor:
            fails.append(f"{who}: expected indoors")
        if exp.get("no_make_up") and s.minutes > planned.minutes:
            fails.append(f"{who}: stacked a make-up session ({s.label()})")
        missing = exp.get("codes", set()) - codes
        if missing:
            fails.append(f"{who}: missing reasons {sorted(missing)} (got {sorted(codes)})")
        if "moved_to" in exp and dec.moved_to != exp["moved_to"]:
            fails.append(f"{who}: expected the key session moved to {exp['moved_to']}, got {dec.moved_to}")
    return fails
