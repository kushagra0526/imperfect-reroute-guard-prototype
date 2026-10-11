"""The founder's morning, 10 scripted days, and the held-out seasons → out/report.html, out/report.json

    python demo.py
"""
import html
import json
import sys
from datetime import timedelta
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from reroute import guard  # noqa: E402
from reroute.plan import Session  # noqa: E402
from reroute.scenarios import ALL, PLAN, check, play  # noqa: E402


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rows, results = [], {}
    for f in ALL:
        sc = f()
        r = play(sc)
        fails = check(sc, r)
        results[sc["id"]] = (sc, r)
        cell = lambda who: (r[who]["day"].session.label() if r[who]["day"] else "busy",
                            [c for c, _ in r[who]["day"].reasons] if r[who]["day"] else [])
        rows.append({"id": sc["id"], "title": sc["title"], "planned": PLAN[sc["day"]].label(),
                     "static": cell("static plan"), "catchup": cell("catch-up coach"), "reroute": cell("reroute"),
                     "note": r["reroute"]["day"].note, "pass": not fails, "fails": fails})

    sc, r = results["founder-morning"]
    d = sc["day"]
    fm = r["reroute"]["day"]
    fu = r["reroute"]["followup"]
    print("\n== The founder's morning (imperfect.co/blog/welcome), replayed on synthetic data")
    print(f"   {d:%a %d %b}: {sc['title']}. Plan: {PLAN[d].label()}")
    print(f"   static plan:    {r['static plan']['day'].session.label()}")
    print(f"   catch-up coach: {r['catch-up coach']['day'].session.label()}  "
          f"{[c for c, _ in r['catch-up coach']['day'].reasons]}")
    print(f"   reroute:        {fm.session.label()}")
    for c, why in fm.reasons:
        print(f"                     {c}: {why}")
    print(f"                   → {fm.note}")
    print(f"   next morning (throat clear, 7+ h sleep): {fu.session.label()} {fu.session.note}")

    # the guard on an LLM-style proposal for that morning
    prop = Session("long", 110, note="LLM: 'Stay on track for your 50k, get out for nearly two hours.'")
    from reroute.season import run
    from reroute.coach import Static
    from reroute import signals
    _, _, raw = run(sc["life"], PLAN, max(PLAN), Static(PLAN), min(PLAN), d, seed=7)
    sig = signals.clean(raw, 185)
    verdict, reasons, allowed = guard.check(prop, d, sig, {})
    print(f"\n== Guard on a model's proposal: \"{prop.note[5:]}\" → {verdict}: {allowed.label()}")
    for c, why in reasons:
        print(f"     {c}: {why}")

    print("\n== 10 scripted days (expected answers written first)")
    for x in rows:
        print(f"   [{'PASS' if x['pass'] else 'FAIL'}] {x['title']}")
        print(f"        plan {x['planned']} | static {x['static'][0]} | catch-up {x['catchup'][0]} {x['catchup'][1]} | "
              f"reroute {x['reroute'][0]} {x['reroute'][1]}")
    ho = json.loads((HERE / "out" / "eval_heldout.json").read_text())["summary"] \
        if (HERE / "out" / "eval_heldout.json").exists() else None
    if ho:
        print(f"\n== Held-out: {ho['seasons']} random seasons (seeds 6-25)")
        for k in ("static plan", "catch-up coach", "reroute (raw data)", "reroute"):
            m = ho[k]
            print(f"   {k:20s} sick-day hard {m['sick_hard']:3d} · jet-lag keys {m['jetlag_key']:3d} · "
                  f"short-sleep keys {m['short_sleep_key']:3d} · back-to-back {m['back_to_back_keys']:3d} · "
                  f"ramp days {m['ramp_breach_days']:3d} · fitness {m['fitness_ctl']}")
        print(f"   same reroute logic, raw vs clean data: {ho['flips_raw_vs_clean']} different decisions")

    week = []
    for k in range(-1, 6):
        x = d + timedelta(days=k)
        week.append({"date": f"{x:%a %d}", "plan": PLAN[x].label(),
                     "static": r["static plan"]["executed"].get(x, None) and r["static plan"]["executed"][x].label(),
                     "catchup": r["catch-up coach"]["executed"].get(x) and r["catch-up coach"]["executed"][x].label(),
                     "reroute": r["reroute"]["executed"].get(x) and r["reroute"]["executed"][x].label()})
    data = {"founder": {"date": f"{d:%a %d %b}", "planned": PLAN[d].label(),
                        "static": r["static plan"]["day"].session.label(),
                        "catchup": r["catch-up coach"]["day"].session.label(),
                        "reroute": fm.session.label(), "reasons": fm.reasons, "note": fm.note,
                        "followup": fu.session.label()},
            "guard": {"proposal": prop.note, "verdict": verdict, "allowed": allowed.label(), "reasons": reasons},
            "scenarios": rows, "heldout": ho}
    (HERE / "out").mkdir(exist_ok=True)
    (HERE / "out" / "report.json").write_text(json.dumps(data, indent=1, default=str))
    (HERE / "out" / "report.html").write_text(render(data), encoding="utf-8")
    print("\nwrote out/report.html, out/report.json")
    return 0


def render(dt):
    e = html.escape
    f, g, ho = dt["founder"], dt["guard"], dt["heldout"]
    chip = lambda codes: "".join(f'<span class="chip">{e(c)}</span>' for c in codes)
    scen = "".join(
        f"<tr><td>{e(x['title'])}</td><td>{e(x['planned'])}</td>"
        f"<td class=\"{'bad' if x['reroute'][1] and x['static'][0] == x['planned'] else ''}\">{e(x['static'][0])}</td>"
        f"<td class=\"{'bad' if x['catchup'][1] and x['id'] not in ('bad-nights',) else ''}\">{e(x['catchup'][0])}<br>{chip(x['catchup'][1])}</td>"
        f"<td class=\"good\">{e(x['reroute'][0])}<br>{chip(x['reroute'][1])}</td>"
        f"<td>{'✓' if x['pass'] else '✗'}</td></tr>" for x in dt["scenarios"])
    ho_html = ""
    if ho:
        rowsx = ""
        for k in ("static plan", "catch-up coach", "reroute (raw data)", "reroute"):
            m = ho[k]
            cls = ' class="me"' if k == "reroute" else ""
            rowsx += (f"<tr{cls}><td>{e(k)}</td><td>{m['sick_hard']}</td><td>{m['jetlag_key']}</td><td>{m['short_sleep_key']}</td>"
                      f"<td>{m['back_to_back_keys']}</td><td>{m['ramp_breach_days']}</td>"
                      f"<td>{m['key_sessions_done']}/{m['key_sessions_planned']}</td><td>{m['fitness_ctl']}</td></tr>")
        ho_html = f"""<section><h2>Held-out: {ho['seasons']} random 20-week seasons (seeds 6–25), run once after the code was frozen in git</h2>
<table class="num"><tr><th></th><th>hard while sick</th><th>key on jet-lag morning</th><th>key after &lt;6 h sleep</th><th>keys back to back</th><th>2-week ramp &gt;130% (days)</th><th>key sessions</th><th>race-day fitness (CTL)</th></tr>{rowsx}</table>
<p class="note">Same reroute logic on raw data vs cleaned data: <b>{ho['flips_raw_vs_clean']}</b> different decisions. The catch-up coach collapses for athletes east of UTC (sleep dated by UTC reads as 0 h).
reroute pays for safety with ~{(1 - ho['reroute']['fitness_ctl'] / ho['static plan']['fitness_ctl']):.0%} lower CTL than the static plan, which trained hard on {ho['static plan']['sick_hard']} sick days.</p></section>"""
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>reroute report</title>
<style>
:root{{--bg:#0f1012;--card:#18191c;--ink:#ecebe6;--mute:#9a978f;--line:#2b2a2e;--good:#58c08d;--bad:#ef7a66;--acc:#f7b267}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,Segoe UI,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:28px 16px}} h1{{margin:0 0 4px;font-size:26px}} h2{{font-size:17px;margin:0 0 10px}}
.sub{{color:var(--mute);margin-bottom:18px}} section{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:14px}}
table{{border-collapse:collapse;width:100%;font-size:14px}} td,th{{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}} th{{color:var(--mute);font-weight:500}}
.num td:not(:first-child),.num th:not(:first-child){{text-align:right}} tr.me td{{color:var(--good);font-weight:600}}
.chip{{display:inline-block;font-size:11px;padding:1px 6px;border:1px solid var(--line);border-radius:999px;margin:2px 3px 0 0;color:var(--mute)}}
.bad{{color:var(--bad)}} .good{{color:var(--good)}} .note{{color:var(--mute);font-size:13px;margin:8px 0 0}}
.three{{display:grid;grid-template-columns:1fr 1fr 1.4fr;gap:12px}} @media(max-width:860px){{.three{{grid-template-columns:1fr}}}}
.card{{border:1px solid var(--line);border-radius:10px;padding:12px}} .card b{{display:block;font-size:22px;margin:4px 0}}
.card .k{{color:var(--mute);font-size:13px}} ul{{margin:6px 0;padding-left:18px}}
</style></head><body><main>
<h1>reroute: Waze for a training plan, with a guard</h1>
<div class="sub">Synthetic athlete, 16-week 50 km trail plan. Every result below is computed. Not medical advice.
Unofficial prototype by Kushagra Pratap Singh. Not affiliated with Imperfect.</div>
<section><h2>The morning from "An Imperfect Journey": jet-lagged after Florence → Mexico City, 4.6 h sleep, a cold coming on. Plan: {e(f['planned'])}</h2>
<div class="three">
<div class="card"><span class="k">static plan</span><b class="bad">{e(f['static'])}</b><span class="k">"get out there and run nearly two hours"</span></div>
<div class="card"><span class="k">catch-up coach (raw data)</span><b>{e(f['catchup'])}</b><span class="k">eases off only because HRV dipped; it has no jet-lag or symptom check, so 45 min with a cold</span></div>
<div class="card"><span class="k">reroute</span><b class="good">{e(f['reroute'])}</b>
<ul>{''.join(f'<li><b style="display:inline;font-size:14px">{e(c)}</b> {e(w)}</li>' for c, w in f['reasons'])}</ul>
<span class="k">→ {e(f['note'])}</span><br><span class="k">Next morning, throat clear, 7+ h sleep: <span class="good">{e(f['followup'])}</span></span></div>
</div></section>
<section><h2>Guard on a model's proposal for that morning → {e(g['verdict'])}: {e(g['allowed'])}</h2>
<p class="note" style="margin-top:0">{e(g['proposal'])}</p><ul>{''.join(f'<li><b>{e(c)}</b> {e(w)}</li>' for c, w in g['reasons'])}</ul>
<p class="note">The guard reads the cleaned wearable data itself, so whatever numbers the model was given can't argue it out of these.</p></section>
<section><h2>10 scripted days (the expected answer was written before running)</h2>
<table><tr><th>day</th><th>plan</th><th>static</th><th>catch-up (raw data)</th><th>reroute</th><th></th></tr>{scen}</table></section>
{ho_html}
</main></body></html>"""


if __name__ == "__main__":
    raise SystemExit(main())
