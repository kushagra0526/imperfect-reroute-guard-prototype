"""Random 20-week seasons (4 base + 16 build) under every coach.

    python evaluate_seasons.py dev        # seeds 1-5, used while building
    python evaluate_seasons.py heldout    # seeds 6-25, run once after the code was frozen in git
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

from reroute.metrics import flips, score
from reroute.season import season

SETS = {"dev": range(1, 6), "heldout": range(6, 26)}


def main(name):
    total = defaultdict(lambda: defaultdict(float))
    flip_total, per_seed = 0, {}
    for seed in SETS[name]:
        out, life, plan = season(seed)
        race = max(plan)
        per_seed[seed] = {}
        for coach, (dec, ex) in out.items():
            m = score(life, ex, race, plan)
            per_seed[seed][coach] = m
            for k, v in m.items():
                total[coach][k] += v
        f = len(flips(out["reroute (raw data)"][0], out["reroute"][0]))
        per_seed[seed]["flips_raw_vs_clean"] = f
        flip_total += f
        print(seed, {c: (m["sick_hard"], m["fitness_ctl"]) for c, m in per_seed[seed].items() if isinstance(m, dict)}, flush=True)
    n = len(SETS[name])
    summary = {c: {k: (round(v / n, 1) if k == "fitness_ctl" else int(v)) for k, v in m.items()} for c, m in total.items()}
    summary["flips_raw_vs_clean"] = flip_total
    summary["seasons"] = n
    Path("out").mkdir(exist_ok=True)
    Path(f"out/eval_{name}.json").write_text(json.dumps({"summary": summary, "per_seed": per_seed}, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dev")
