"""Wearable data → daily signals. Two pipelines over the same raw records.

clean():  what a coach should see
  - one activity per real session (Garmin, Strava and Apple Health all send the same run)
  - HRV compared only with the same metric from the same kind of source: Garmin/Oura report
    overnight RMSSD, Apple Health stores SDNN, typically 30-50% higher in the same person
  - sleep dated by the *local* wake-up day; a change of UTC offset is travel (jet lag)
  - a night without data is unknown, never 0 hours
  - sensor artifacts dropped
naive(): the shortcut version, kept for comparison
"""
from collections import defaultdict
from datetime import timedelta
from statistics import mean, pstdev

from .plan import intensity_frac

SOURCE_RANK = {"garmin": 0, "apple": 1, "strava": 2}
HRV_RANGE = {"rmssd": (8, 200), "sdnn": (10, 250)}
BASELINE_MIN = 7       # nights of the *same* metric before HRV is used
BASELINE_DAYS = 28


def _local(dt_utc, offset_min):
    return dt_utc + timedelta(minutes=offset_min)


def intensity(avg_hr, hr_max):
    return intensity_frac(avg_hr / hr_max) if avg_hr else 1.0


def _same_session(a, b):
    return (a["sport"] == b["sport"]
            and abs((a["start_utc"] - b["start_utc"]).total_seconds()) <= 300
            and abs(a["minutes"] - b["minutes"]) <= 0.1 * max(a["minutes"], b["minutes"]))


def dedupe(acts):
    """Group duplicates; keep the record from the highest-ranked source that has heart rate."""
    groups = []
    for a in sorted(acts, key=lambda x: x["start_utc"]):
        for g in groups:
            if _same_session(g[0], a):
                g.append(a)
                break
        else:
            groups.append([a])
    out = []
    for g in groups:
        best = min(g, key=lambda x: (x.get("avg_hr") is None, SOURCE_RANK.get(x["source"], 9)))
        out.append({**best, "sources": sorted({x["source"] for x in g})})
    return out


def _load_by_day(acts, hr_max, use_local=True):
    load = defaultdict(float)
    for a in acts:
        d = (_local(a["start_utc"], a["tz_min"]) if use_local else a["start_utc"]).date()
        load[d] += a["minutes"] * intensity(a.get("avg_hr"), hr_max)
    return load


def clean(raw, hr_max):
    acts = dedupe(raw["activities"])
    load = _load_by_day(acts, hr_max)

    sleep, offset = {}, {}
    for s in raw["sleep"]:
        wake = _local(s["end_utc"], s["tz_min"]).date()
        hours = (s["end_utc"] - s["start_utc"]).total_seconds() / 3600
        if hours > sleep.get(wake, 0):        # main sleep of that wake-up day (naps ignored)
            sleep[wake] = hours
            offset[wake] = s["tz_min"]

    for d, tz in raw.get("phone_tz", {}).items():   # the phone knows its time zone even with no sleep data
        offset[d] = tz

    nights = []
    for h in raw["hrv"]:
        lo, hi = HRV_RANGE[h["metric"]]
        if lo <= h["value"] <= hi:
            nights.append((_local(h["end_utc"], h["tz_min"]).date(), h["metric"], h["value"]))
    nights.sort()
    hrv = {}
    for i, (d, metric, v) in enumerate(nights):
        prior = [x for (dd, m, x) in nights[:i] if m == metric and (d - dd).days <= BASELINE_DAYS]
        if len(prior) >= BASELINE_MIN and pstdev(prior) > 0:
            mu, sd = mean(prior), pstdev(prior)
            last3 = [x for (dd, m, x) in nights[max(0, i - 2):i + 1] if m == metric and (d - dd).days <= 3]
            hrv[d] = {"metric": metric, "value": v, "z": (v - mu) / sd, "z3": (mean(last3) - mu) / sd,
                      "n": len(prior)}
        else:
            hrv[d] = {"metric": metric, "value": v, "z": None, "z3": None, "n": len(prior)}

    return {"activities": acts, "load": load, "sleep": sleep, "hrv": hrv, "offset": offset,
            "checkins": raw.get("checkins", {}), "aqi": raw.get("aqi", {}), "pipeline": "clean"}


def naive(raw, hr_max):
    """Every record counts; sleep by UTC date; missing nights are 0 h; one HRV baseline for all metrics."""
    acts = [dict(a, sources=[a["source"]]) for a in raw["activities"]]
    load = _load_by_day(acts, hr_max, use_local=False)
    sleep = defaultdict(float)
    for s in raw["sleep"]:
        sleep[s["end_utc"].date()] += (s["end_utc"] - s["start_utc"]).total_seconds() / 3600
    nights = sorted((h["end_utc"].date(), h["metric"], h["value"]) for h in raw["hrv"])
    hrv = {}
    for i, (d, metric, v) in enumerate(nights):
        prior = [x for (dd, _, x) in nights[:i] if (d - dd).days <= BASELINE_DAYS]
        z = (v - mean(prior)) / pstdev(prior) if len(prior) >= BASELINE_MIN and pstdev(prior) > 0 else None
        last3 = [x for (dd, _, x) in nights[max(0, i - 2):i + 1]]
        z3 = (mean(last3) - mean(prior)) / pstdev(prior) if z is not None else None
        hrv[d] = {"metric": metric, "value": v, "z": z, "z3": z3, "n": len(prior)}
    return {"activities": acts, "load": load, "sleep": _ZeroDefault(sleep), "hrv": hrv, "offset": {},
            "checkins": raw.get("checkins", {}), "aqi": raw.get("aqi", {}), "pipeline": "naive"}


class _ZeroDefault(dict):
    """A missing night reads as 0 hours: the naive bug."""
    def get(self, k, default=None):
        return super().get(k, 0.0)
