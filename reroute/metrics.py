"""Score what an athlete actually did in a season. Truth comes from the Life, not from the data.
The ramp reference matches the guard: previous 14 days, or the best 14-day block already handled
in the 4 weeks before."""
from datetime import timedelta

from .guard import ABOVE_NECK, BELOW_NECK, JETLAG_MIN, RAMP, RAMP_FLOOR


def _load(ex, end, days):
    return sum(ex[end - timedelta(days=k)].load for k in range(days) if end - timedelta(days=k) in ex)


def score(life, executed, race_day, plan=None):
    days = sorted(executed)
    m = {"sick_hard": 0, "return_too_fast": 0, "jetlag_key": 0, "short_sleep_key": 0,
         "back_to_back_keys": 0, "ramp_breach_days": 0, "long_150_done": 0}
    for d in days:
        s = executed[d]
        sym = life.symptoms.get(d, set())
        if sym & BELOW_NECK and s.kind != "rest":
            m["sick_hard"] += 1
        elif sym & ABOVE_NECK and (s.key or s.minutes > 30):
            m["sick_hard"] += 1
        if s.key and s.kind != "race" and not sym:
            sick = [k for k in range(1, 8) if life.symptoms.get(d - timedelta(days=k), set()) & BELOW_NECK]
            clear = [k for k in range(1, 3) if not life.symptoms.get(d - timedelta(days=k))]
            if len(sick) >= 2 and len(clear) < 2:
                m["return_too_fast"] += 1
        prev = d - timedelta(days=1)
        if s.key and abs(life.tz.get(d, life.home_tz) - life.tz.get(prev, life.home_tz)) >= JETLAG_MIN:
            m["jetlag_key"] += 1
        if s.key and s.kind != "race" and life.sleep.get(d, 7.5) < 6 and d not in life.watch_off:
            m["short_sleep_key"] += 1
        if s.key and prev in executed and executed[prev].key:
            m["back_to_back_keys"] += 1
        p14 = max([_load(executed, d - timedelta(days=14), 14)]
                  + [_load(executed, d - timedelta(days=14 + 7 * k), 14) for k in range(1, 5)])
        if (d - days[0]).days >= 42 and s.load > 0 and s.kind != "race"                 and p14 >= RAMP_FLOOR and _load(executed, d, 14) > RAMP * p14:
            m["ramp_breach_days"] += 1
        if s.kind == "long" and s.minutes >= 150:
            m["long_150_done"] += 1
    ctl = 0.0
    for d in days:
        if d >= race_day:
            break
        ctl += (executed[d].load - ctl) / 42
    m["fitness_ctl"] = round(ctl, 1)
    if plan:
        planned_keys = [d for d in plan if plan[d].key and plan[d].kind != "race"]
        m["key_sessions_done"] = sum(1 for d in executed if executed[d].key and executed[d].kind != "race")
        m["key_sessions_planned"] = len(planned_keys)
    return m


def flips(dec_a, dec_b):
    """Days where the same coach decided differently on raw vs clean data."""
    out = []
    for a, b in zip(dec_a, dec_b):
        if a and b and (a.session.kind, a.session.minutes) != (b.session.kind, b.session.minutes):
            out.append((b.date, a, b))
    return out
