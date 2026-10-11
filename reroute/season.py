"""A synthetic athlete living a training season, day by day.

Each morning the wearables send last night (sleep, HRV) and yesterday's activities; the coach
decides; the athlete does it (unless busy or too sick); the activity is recorded by whatever
devices and apps are connected. Life events are explicit, so scenarios can script them and
random seasons can sample them.
"""
import random
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from . import guard, signals
from .coach import CatchUp, Rerouter, Static
from .plan import HR_FRAC, REST, fifty_k_plan

HR_MAX = 185


@dataclass
class Life:
    home_tz: int = -360                                   # minutes from UTC
    tz: dict = field(default_factory=dict)                # date -> offset where you wake up
    symptoms: dict = field(default_factory=dict)          # date -> set
    busy: set = field(default_factory=set)                # can't train at all
    sleep: dict = field(default_factory=dict)             # date -> hours (overrides normal)
    hrv_drop: dict = field(default_factory=dict)          # date -> fraction lower
    watch_off: set = field(default_factory=set)           # nights with no data
    switch_to_apple: object = None                        # date the athlete changes watch
    strava_from: object = None                            # Strava also uploads every activity
    apple_mirror_from: object = None                      # Garmin -> Apple Health sync turned on
    aqi: dict = field(default_factory=dict)
    rmssd_base: float = 55.0


def offset(life, d):
    return life.tz.get(d, life.home_tz)


def _night(life, d, rng):
    """Sleep ending on the morning of d and that night's HRV, as the devices report them."""
    if d in life.watch_off:
        return [], []
    tz = offset(life, d)
    hours = life.sleep.get(d, rng.uniform(6.8, 8.2))
    wake_local = datetime.combine(d, time(6, 30)) + timedelta(minutes=rng.randint(-30, 40))
    end = wake_local - timedelta(minutes=tz)
    start = end - timedelta(hours=hours)
    apple = life.switch_to_apple is not None and d >= life.switch_to_apple
    src = "apple" if apple else "garmin"
    rmssd = life.rmssd_base * (1 - life.hrv_drop.get(d, 0)) * (1 - (0.2 if life.symptoms.get(d) else 0)) + rng.gauss(0, 4)
    hrv = {"source": src, "metric": "sdnn" if apple else "rmssd",
           "value": round(rmssd * 1.45 + rng.gauss(0, 4) if apple else rmssd, 1), "end_utc": end, "tz_min": tz}
    return [{"source": src, "start_utc": start, "end_utc": end, "tz_min": tz}], [hrv]


def _activity(life, d, s, rng):
    if s.kind == "rest":
        return []
    tz = offset(life, d)
    start = datetime.combine(d, time(7, 15)) - timedelta(minutes=tz) + timedelta(minutes=rng.randint(0, 50))
    hr = round(HR_FRAC[s.kind] * HR_MAX + rng.gauss(0, 3))
    apple = life.switch_to_apple is not None and d >= life.switch_to_apple
    base = {"source": "apple" if apple else "garmin", "sport": "run" if s.kind != "mobility" else "yoga",
            "start_utc": start, "minutes": s.minutes, "avg_hr": hr, "tz_min": tz}
    out = [base]
    if life.strava_from and d >= life.strava_from:
        out.append({**base, "source": "strava", "start_utc": start + timedelta(seconds=rng.randint(0, 90)),
                    "minutes": s.minutes + rng.choice([-1, 0, 1])})
    if not apple and life.apple_mirror_from and d >= life.apple_mirror_from:
        out.append({**base, "source": "apple", "avg_hr": None})
    return out


def run(life, plan, race_day, coach, start, end, seed=0, pipeline="clean", history=None):
    """Simulate start..end (inclusive). Returns (decisions, executed, raw)."""
    raw = history or {"activities": [], "sleep": [], "hrv": [], "checkins": {}, "aqi": {}}
    decisions, executed = [], {}
    d = start
    while d <= end:
        rng = random.Random(f"{seed}-{d}")          # same nights for every coach
        sl, hv = _night(life, d, rng)
        raw["sleep"] += sl; raw["hrv"] += hv
        if life.symptoms.get(d):
            raw["checkins"][d] = {"symptoms": set(life.symptoms[d])}
        raw.setdefault("phone_tz", {})[d] = offset(life, d)
        if d in life.aqi:
            raw["aqi"][d] = life.aqi[d]
        sig = (signals.clean if pipeline == "clean" else signals.naive)(raw, HR_MAX)
        if d in life.busy:
            dec = coach.missed(d) if hasattr(coach, "missed") else None
            s = REST
            decisions.append(dec)
        else:
            dec = coach.decide(d, sig)
            s = dec.session
            if guard.symptoms(sig, d) & guard.BELOW_NECK:   # too sick, whatever the app says
                s = REST
            decisions.append(dec)
        executed[d] = s
        raw["activities"] += _activity(life, d, s, random.Random(f"{seed}-{d}-act"))
        d += timedelta(days=1)
    return decisions, executed, raw


def random_life(seed, race_day, weeks=16):
    rng = random.Random(seed)
    first = race_day - timedelta(days=7 * weeks - 1)   # events fall in the 16 build weeks
    day = lambda lo, hi: first + timedelta(days=rng.randint(lo, hi))
    L = Life(home_tz=rng.choice([-480, -360, 0, 60, 330, 540]))
    # a cold (above the neck), maybe a flu (below, then above)
    c = day(14, 90)
    for k in range(rng.randint(3, 5)):
        L.symptoms[c + timedelta(days=k)] = {rng.choice(["sore throat", "runny nose", "congestion"])}
    if rng.random() < 0.6:
        f = day(20, 95)
        n = rng.randint(2, 3)
        for k in range(n):
            L.symptoms[f + timedelta(days=k)] = {"fever", "body aches"}
        for k in range(n, n + 2):
            L.symptoms[f + timedelta(days=k)] = {"congestion"}
    # trips across time zones
    for _ in range(rng.randint(1, 2)):
        t0 = day(7, 95)
        shift = rng.choice([-1, 1]) * rng.randint(5, 10) * 60
        stay = rng.randint(4, 9)
        L.busy.add(t0)
        for k in range(1, stay + 1):
            L.tz[t0 + timedelta(days=k)] = L.home_tz + shift
        L.sleep[t0 + timedelta(days=1)] = rng.uniform(4.0, 5.5)
        L.sleep[t0 + timedelta(days=stay + 1)] = rng.uniform(4.5, 5.8)
    for _ in range(rng.randint(3, 6)):
        L.busy.add(day(1, 100))
    for _ in range(rng.randint(4, 8)):
        b = day(1, 105)
        L.sleep[b] = rng.uniform(4.3, 5.4); L.hrv_drop[b] = 0.25
    for _ in range(rng.randint(3, 6)):
        L.watch_off.add(day(10, 105))
    L.switch_to_apple = day(28, 84)
    L.strava_from = day(7, 60)
    L.apple_mirror_from = day(7, 40)
    for _ in range(rng.randint(0, 3)):
        L.aqi[day(10, 100)] = rng.randint(160, 220)
    return L


def season(seed, race_day=None):
    """One random season under all coaches. Returns {coach_name: (decisions, executed)} and life."""
    race_day = race_day or datetime(2027, 4, 10).date()
    plan = fifty_k_plan(race_day)
    start, life = min(plan), random_life(seed, race_day)
    out = {}
    for name, mk, pipe in [("static plan", lambda: Static(plan), "clean"),
                           ("catch-up coach", lambda: CatchUp(plan), "naive"),
                           ("reroute (raw data)", lambda: Rerouter(plan, race_day), "naive"),
                           ("reroute", lambda: Rerouter(plan, race_day), "clean")]:
        dec, ex, _ = run(life, plan, race_day, mk(), start, race_day, seed=seed, pipeline=pipe)
        out[name] = (dec, ex)
    return out, life, plan
