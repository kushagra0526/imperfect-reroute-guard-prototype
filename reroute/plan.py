"""Training plan: sessions, load, and a 16-week 50 km trail plan."""
from dataclasses import dataclass, replace
from datetime import timedelta

KEY = {"long", "tempo", "intervals", "race"}
HR_FRAC = {"easy": 0.70, "long": 0.72, "tempo": 0.82, "intervals": 0.88, "cross": 0.65,
           "mobility": 0.55, "race": 0.78}


def intensity_frac(f):
    """Load per minute from average heart rate as a fraction of max (same rule for plans and wearables)."""
    return 0.5 if f < 0.60 else 1.0 if f < 0.75 else 1.4 if f < 0.85 else 1.8


@dataclass(frozen=True)
class Session:
    kind: str
    minutes: int
    indoor: bool = False
    note: str = ""

    @property
    def key(self):
        return self.kind in KEY

    @property
    def load(self):
        return 0.0 if self.kind == "rest" else self.minutes * intensity_frac(HR_FRAC[self.kind])

    def label(self):
        if self.kind == "rest":
            return "Rest"
        s = f"{'Yoga / mobility' if self.kind == 'mobility' else self.kind.capitalize()} {self.minutes} min"
        return s + (" (indoors)" if self.indoor else "")

    def with_(self, **kw):
        return replace(self, **kw)


REST = Session("rest", 0)


def fifty_k_plan(race_day, weeks=16, base_weeks=4):
    """Mon rest · Tue intervals · Wed easy · Thu tempo · Fri easy · Sat long · Sun easy.
    base_weeks of steady running first, then ~5%/week with every 4th week lighter (x0.85),
    a 2-week taper, race on race_day."""
    start = race_day - timedelta(days=7 * (weeks + base_weeks) - 1)
    start -= timedelta(days=start.weekday())  # Monday
    plan = {}
    d = start
    while d < race_day:
        w = (d - start).days // 7 - base_weeks
        if w < 0:
            f = 0.9
        elif w >= weeks - 2:
            f = (1.05 ** (weeks - 3)) * (0.7 if w == weeks - 2 else 0.5)
        else:
            f = (1.05 ** w) * (0.85 if w % 4 == 3 else 1.0)
        dow = d.weekday()
        s = [REST, Session("intervals", 45), Session("easy", 40), Session("tempo", 40),
             Session("easy", 30), Session("long", 85), Session("easy", 45)][dow]
        if s.kind != "rest":
            s = s.with_(minutes=int(round(min(s.minutes * f, 210 if s.kind == "long" else 75) / 5) * 5))
        plan[d] = s
        d += timedelta(days=1)
    plan[race_day] = Session("race", 360)
    return plan
