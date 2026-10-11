"""Check any proposed session (e.g. from the LLM coach) before the athlete sees it.

The guard reads the *cleaned* signals itself, so a model that was handed duplicated runs or a
mixed HRV baseline can't talk it into a bad day. Returns OK / MODIFY / BLOCK, the reasons, and
the session it would allow instead.
"""
from datetime import timedelta

from .plan import REST, Session

ABOVE_NECK = {"runny nose", "sore throat", "congestion", "sneezing"}
BELOW_NECK = {"fever", "chest tightness", "body aches", "nausea", "diarrhea"}
JETLAG_MIN = 300          # UTC offset change, minutes
SHORT_SLEEP = 6.0
LOW_HRV_Z = -1.5          # last night...
LOW_HRV_Z3 = -1.0         # ...and the 3-night average: one noisy night is not a signal
RAMP = 1.30               # last 14 days vs the 14 before (Nielsen et al. 2014: >30% over 2 weeks)
RAMP_FLOOR = 300          # don't apply the ramp rule on a tiny base


def symptoms(sig, d):
    return set(sig["checkins"].get(d, {}).get("symptoms", ()))


def tz_shift(sig, d):
    """UTC-offset change (minutes) on wake-up day d versus the previous known wake-up."""
    off = sig["offset"]
    if d not in off:
        return 0
    prev = [x for x in off if x < d and (d - x).days <= 3]
    return abs(off[d] - off[max(prev)]) if prev else 0


def window_load(sig_load, end, days):
    """Wearable-recorded load in (end-days, end]."""
    return sum(sig_load.get(end - timedelta(days=k), 0.0) for k in range(days))


def _cap(s, minutes):
    """Easy, at most `minutes` (rest stays rest)."""
    return s if s.kind == "rest" else Session("easy", min(minutes, max(s.minutes, 20)) if s.key else min(minutes, s.minutes))


def ramp_reference(load, d):
    """The 14 days before the current window, or the best 14-day block in the 4 weeks before
    that: coming back to a load you already handled is not a new ramp."""
    prev = window_load(load, d - timedelta(days=14), 14)
    earlier = [window_load(load, d - timedelta(days=14 + 7 * k), 14) for k in range(1, 5)]
    return max([prev] + earlier)


def check(prop: Session, d, sig, executed, upcoming=None):
    """executed: {date: Session} prescribed and done (up to d-1), used for key spacing.
    upcoming: {date: Session} planned after d. Load comes from the wearable signals."""
    upcoming = upcoming or {}
    reasons, s = [], prop
    sym = symptoms(sig, d)
    below, above = sym & BELOW_NECK, sym & ABOVE_NECK
    if below and s.kind != "rest":
        reasons.append(("SICK_BELOW_NECK", f"{', '.join(sorted(below))}: rest until 24 h symptom-free"))
        s = REST
    elif above and (prop.key or prop.minutes > 30):
        reasons.append(("SICK_ABOVE_NECK", f"{', '.join(sorted(above))}: easy 30 min at most, or rest"))
        s = _cap(s, 30)
    if prop.key and not sym:
        sick_days = [d - timedelta(days=k) for k in range(1, 8) if symptoms(sig, d - timedelta(days=k)) & BELOW_NECK]
        clear = [d - timedelta(days=k) for k in range(1, 3) if not symptoms(sig, d - timedelta(days=k))]
        if len(sick_days) >= 2 and len(clear) < 2:
            reasons.append(("RETURN_AFTER_ILLNESS", f"{len(sick_days)} days with {', '.join(sorted(symptoms(sig, sick_days[0]) & BELOW_NECK))} "
                            "this week: easy only for the first 2 symptom-free days"))
            s = _cap(s, 45)
    if prop.key and tz_shift(sig, d) >= JETLAG_MIN:
        reasons.append(("JET_LAG", f"first morning after a {tz_shift(sig, d) / 60:.0f} h time-zone change"))
        s = _cap(s, 40)
    sl, hv = sig["sleep"].get(d), sig["hrv"].get(d)
    if prop.key and sl is not None and sl < SHORT_SLEEP:
        reasons.append(("SHORT_SLEEP", f"slept {sl:.1f} h"))
        s = _cap(s, 45)
    if prop.key and hv and hv["z"] is not None and hv["z"] <= LOW_HRV_Z and hv["z3"] <= LOW_HRV_Z3:
        reasons.append(("LOW_HRV", f"HRV {hv['z']:+.1f} SD last night, {hv['z3']:+.1f} SD over 3 nights, "
                                   f"vs your {hv['metric'].upper()} baseline"))
        s = _cap(s, 45)
    recovery = {c for c, _ in reasons} & {"SICK_ABOVE_NECK", "JET_LAG", "SHORT_SLEEP", "LOW_HRV"}
    if len(recovery) >= 2 and s.kind != "rest":
        s = Session("mobility", 30, note="yoga / mobility: active recovery")
    if s.key:
        near = [x for x in (d - timedelta(days=1),) if x in executed and executed[x].key]
        near += [x for x in (d + timedelta(days=1),) if x in upcoming and upcoming[x].key]
        if near:
            reasons.append(("KEY_SPACING", f"another key session on {near[0]:%a %d %b}; keep 48 h between them"))
            s = Session("easy", min(45, s.minutes))
    prev14 = ramp_reference(sig["load"], d)
    last13 = window_load(sig["load"], d - timedelta(days=1), 13)
    if prev14 >= RAMP_FLOOR and last13 + s.load > RAMP * prev14 and s.kind not in ("rest", "race"):
        room = RAMP * prev14 - last13
        mins = int(max(0, room) / max(s.load / max(s.minutes, 1), 1e-9) // 5 * 5)
        reasons.append(("RAMP_2W", f"14-day load would be {(last13 + s.load) / prev14:.0%} of your recent level (limit {RAMP:.0%})"))
        s = Session("easy", min(mins, 40)) if mins >= 20 else REST
    if prop.indoor is False and s.kind != "rest" and sig["aqi"].get(d, 0) > 150:
        reasons.append(("AIR_QUALITY", f"AQI {sig['aqi'][d]}: move it indoors"))
        s = s.with_(indoor=True)
    if not reasons:
        return "OK", [], prop
    blocked = s.kind == "rest" and prop.kind != "rest"
    return ("BLOCK" if blocked else "MODIFY"), reasons, s
