"""Three coaches for the same athlete.

Static     "MapQuest": the plan as written. Only a fever or a busy day stops it.
CatchUp    adaptive in the risky way: reacts to whatever numbers it gets and makes up every
           missed session on top of the next day.
Rerouter   "Waze": the guard decides today; a displaced key session is swapped into a later
           easy day (48 h from other keys, not in the last week before the race), else dropped.
           Never stacked.
"""
from dataclasses import dataclass, field
from datetime import timedelta

from . import guard
from .plan import KEY, REST, Session

PRIORITY = {"long": 0, "tempo": 1, "intervals": 2}


@dataclass
class Decision:
    date: object
    planned: Session
    session: Session
    verdict: str = "OK"
    reasons: list = field(default_factory=list)
    moved_to: object = None
    dropped: bool = False
    note: str = ""


class Static:
    name = "static plan"

    def __init__(self, plan):
        self.plan = dict(plan)

    def decide(self, d, sig):
        p = self.plan[d]
        if guard.symptoms(sig, d) & guard.BELOW_NECK:
            return Decision(d, p, REST, "BLOCK", [("SICK_BELOW_NECK", "too sick to train")])
        return Decision(d, p, p)


class CatchUp:
    name = "catch-up coach"

    def __init__(self, plan):
        self.plan = dict(plan)
        self.owed = []

    def decide(self, d, sig):
        p = self.plan[d]
        reasons = []
        s = p
        sl, hv = sig["sleep"].get(d), sig["hrv"].get(d)
        prev14 = guard.window_load(sig["load"], d - timedelta(days=14), 14)
        last14 = guard.window_load(sig["load"], d - timedelta(days=1), 14)
        if guard.symptoms(sig, d) & guard.BELOW_NECK:
            reasons.append(("SICK", "fever: rest")); s = REST
        elif sl is not None and sl < 4:
            reasons.append(("SLEEP_DEBT", f"slept {sl:.1f} h: rest")); s = REST
        elif prev14 > 300 and last14 > 1.5 * prev14:
            reasons.append(("OVERREACHING", f"load {last14 / prev14:.0%} of previous 2 weeks: rest")); s = REST
        elif hv and hv["z"] is not None and hv["z"] <= -1.5:   # single night, as many apps do
            reasons.append(("LOW_HRV", f"HRV {hv['z']:+.1f} SD: easy")); s = Session("easy", min(45, p.minutes))
        elif hv and hv["z"] is not None and hv["z"] >= 1.5 and p.kind != "rest":
            reasons.append(("GREEN_LIGHT", f"HRV {hv['z']:+.1f} SD: +20%")); s = p.with_(minutes=int(p.minutes * 1.2))
        if p.key and not s.key and p.kind != "race":
            self.owed.append(p)
        elif s.kind not in ("rest",) and self.owed and p.kind != "race":
            extra = self.owed.pop(0)                       # make it up today, on top
            kind = extra.kind if PRIORITY.get(extra.kind, 9) <= PRIORITY.get(s.kind, 9) else s.kind
            reasons.append(("MAKE_UP", f"+{extra.label()} you missed"))
            s = Session(kind, s.minutes + extra.minutes)
        return Decision(d, p, s, "MODIFY" if reasons else "OK", reasons)

    def missed(self, d):
        if self.plan[d].key and self.plan[d].kind != "race":
            self.owed.append(self.plan[d])


class Rerouter:
    name = "reroute"

    def __init__(self, plan, race_day):
        self.plan = dict(plan)
        self.race = race_day
        self.done = {}

    def decide(self, d, sig):
        p = self.plan[d]
        upcoming = {x: self.plan[x] for x in (d + timedelta(days=1),) if x in self.plan}
        verdict, reasons, s = guard.check(p, d, sig, self.done, upcoming)
        dec = Decision(d, p, s, verdict, reasons)
        if p.key and not s.key and p.kind != "race":
            self._reschedule(p, d, dec)
        self.done[d] = s
        return dec

    def missed(self, d):
        """The athlete couldn't train (busy): treat today's key session as displaced."""
        p = self.plan[d]
        self.done[d] = REST
        if p.key and p.kind != "race":
            dec = Decision(d, p, REST)
            self._reschedule(p, d, dec)
            return dec
        return None

    def _reschedule(self, p, d, dec):
        cond = {c for c, _ in dec.reasons}
        if p.note.startswith("moved"):                     # moved once already: let it go
            dec.dropped = True
            dec.note = f"{p.label()} dropped: it was already moved once. Not stacked onto another day."
            return
        for k in range(1, 7):
            d2 = d + timedelta(days=k)
            if d2 not in self.plan or (self.race - d2).days < 7:
                break
            q = self.plan[d2]
            if q.kind in KEY and PRIORITY.get(q.kind, 0) <= PRIORITY[p.kind]:
                continue                                   # only bump a less important key
            nb = [self.plan.get(d2 - timedelta(days=1)), self.plan.get(d2 + timedelta(days=1))]
            if d2 - timedelta(days=1) == d:
                nb[0] = dec.session
            if any(x is not None and x.kind in KEY for x in nb):
                continue
            if any(x.kind in KEY and x.note.startswith("moved") for x in self.plan.values() if x is q):
                continue
            self.plan[d2] = p.with_(note=f"moved from {d:%a %d %b}")
            dec.moved_to = d2
            checks = []
            if cond & {"SICK_ABOVE_NECK", "SICK_BELOW_NECK", "RETURN_AFTER_ILLNESS"}:
                checks.append("you're symptom-free")
            if cond & {"SHORT_SLEEP", "JET_LAG", "LOW_HRV"}:
                checks.append("you sleep at least 6 h")
            dec.note = (f"{p.label()} moved to {d2:%a %d %b}"
                        + (f", only if {' and '.join(checks)}; re-checked that morning" if checks else "")
                        + f" (replaces {q.label().lower()}"
                        + (", which is dropped" if q.kind in KEY else "") + ")")
            return
        dec.dropped = True
        dec.note = f"{p.label()} dropped: no safe slot this week. Not stacked onto another day."
