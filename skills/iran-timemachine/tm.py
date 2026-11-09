"""iran-timemachine: replay the plan in trader/plan.json before risking a Rial.

  python tm.py run [--sims 10000] [--days 250] [--hold N] [--setup breakout20] [--seed 7]

Two tests, both with fees and the daily price limit:
  1. Monte Carlo: 10,000 futures of up to --hold sessions, each session drawn at random from this
     stock's own last --days sessions (open/high/low/close relative to the previous close,
     back-adjusted for capital raises and dividends).
  2. History: the same stop/target distances entered at the close of every past session
     (or only sessions where --setup fired) and walked forward through what really happened.

Rules each session: open at/below stop -> out at the open (gap); low <= stop -> stop; high >= target ->
target; both on one day -> stop (conservative). A session LOCKED at the lower limit (high = low =
lower limit, i.e. a sell queue all day) lets nobody sell: the stop waits for the next session.
Still in after --hold sessions -> out at that close. Entry is assumed at the plan's entry price at
the end of day 0 (the rest of the entry day is not simulated).
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "iran-common"))
import iran as I  # noqa: E402

EPS = 0.002


def rel_days(bars, band):
    out = []
    for p, b in zip(bars, bars[1:]):
        pc = p["close"]
        if not pc:
            continue
        r = {k: b[k] / pc for k in ("open", "high", "low", "close")}
        # clip to the band (adjusted ex-date sessions can look like huge moves)
        for k in r:
            r[k] = min(max(r[k], 1 - band), 1 + band)
        r["locked_down"] = (abs(r["high"] - r["low"]) < EPS and r["close"] <= 1 - band + EPS)
        out.append(r)
    return out


def walk(days_iter, entry, stop, target, hold, fb, fs, risk):
    """days_iter yields relative days; returns (outcome, exit_price, sessions, R)."""
    prev = entry
    for n, d in enumerate(days_iter, 1):
        o, h, l, c = prev * d["open"], prev * d["high"], prev * d["low"], prev * d["close"]
        if d.get("locked_down"):   # sell queue all day: nobody can sell, even after --hold
            prev = c
            continue
        if o <= stop:
            ex, out = o, "stop_gap"
        elif l <= stop:
            ex, out = stop, "stop"
        elif h >= target:
            ex, out = target, "target"
        elif n >= hold:
            ex, out = c, "time"
        else:
            prev = c
            continue
        r = (ex * (1 - fs) - entry * (1 + fb)) / risk
        return out, ex, n, r
    return "open", prev, None, (prev * (1 - fs) - entry * (1 + fb)) / risk


def summarize(results):
    n = len(results)
    if not n:
        return None
    cnt = {}
    for o, *_ in results:
        k = "stop" if o.startswith("stop") else o
        cnt[k] = cnt.get(k, 0) + 1
    rs = [r for *_, r in results]
    sess = [s for _, _, s, _ in results if s]
    srt = sorted(rs)
    return {"n": n, "target": cnt.get("target", 0) / n, "stop": cnt.get("stop", 0) / n,
            "gap": sum(1 for o, *_ in results if o == "stop_gap") / n,
            "time": cnt.get("time", 0) / n, "open": cnt.get("open", 0) / n,
            "avg_r": sum(rs) / n, "median_r": srt[n // 2], "p10_r": srt[n // 10], "p90_r": srt[(9 * n) // 10],
            "avg_sessions": sum(sess) / len(sess) if sess else None}


def cmd_run(a):
    cfg = I.config()
    plan = I.read_json("plan.json")
    if not plan:
        I.die("trader/plan.json نیست. اول /iran-exit را اجرا کنید.")
    fb, fs = I.fees(cfg)
    entry, stop, target = plan["entry"], plan["stop"], plan["target"]
    hold = a.hold or plan.get("hold_sessions", 10)
    risk = entry * (1 + fb) - stop * (1 - fs)
    band = plan.get("band_pct") or cfg["band_pct"]
    bars = I.daily(plan["insCode"], days=a.days + 1)
    if len(bars) < 60:
        I.die(f"تاریخچه کافی نیست ({len(bars)} جلسه).")
    rel = rel_days(bars, band)
    rng = random.Random(a.seed)

    mc = []
    for _ in range(a.sims):
        it = (rng.choice(rel) for _ in range(hold + 20))
        mc.append(walk(it, entry, stop, target, hold, fb, fs, risk))
    S = summarize(mc)

    # history
    sd, td = stop / entry, target / entry
    idx = range(20, len(bars) - 1)
    if a.setup:
        if a.setup != "breakout20":
            I.die("فعلاً فقط --setup breakout20 پشتیبانی می‌شود.")
        idx = [i for i in idx if bars[i]["close"] > max(b["close"] for b in bars[i - 20:i])]
    hist = []
    for i in idx:
        e = bars[i]["close"]
        hist.append(walk(iter(rel[i:]), e, e * sd, e * td, hold, fb, fs, e * (1 + fb) - e * sd * (1 - fs)))
    hist = [h for h in hist if h[0] != "open"]
    H = summarize(hist)

    rr = plan.get("rr_after_fees") or ((target * (1 - fs) - entry * (1 + fb)) / risk)
    be = 1 / (1 + rr)
    locked = sum(1 for r in rel if r["locked_down"]) / len(rel)

    def line(name, s):
        if not s:
            print(f"  {name}: داده کافی نیست")
            return
        print(f"  {name} (n={s['n']:,}):  هدف اول {s['target']*100:5.1f}%   حد ضرر اول {s['stop']*100:5.1f}%"
              f" (گپ {s['gap']*100:.1f}%)   پایان مهلت {s['time']*100:5.1f}%")
        print(f"      میانگین R = {s['avg_r']:+.2f}   میانه {s['median_r']:+.2f}   ۱۰٪ بد {s['p10_r']:+.2f}"
              f"   ۱۰٪ خوب {s['p90_r']:+.2f}   میانگین جلسات {s['avg_sessions'] or 0:.1f}")

    print(f"■ ماشین زمان {plan['symbol']}: ورود {I.price(entry)}  حد ضرر {I.price(stop)}  هدف {I.price(target)}"
          f"  نگهداری {hold} جلسه  (R:R پس از کارمزد {rr:.2f})")
    print(f"  نمونه: {len(rel)} جلسه اخیر؛ {locked*100:.1f}% آن‌ها قفل صف فروش بوده‌اند.")
    line(f"مونت‌کارلو {a.sims:,} مسیر", S)
    line("تاریخچه" + (f" (فقط {a.setup})" if a.setup else " (ورود در هر روز)"), H)
    print(f"  نقطه سر به سر: باید بیش از {be*100:.1f}% به هدف برسد (یا میانگین R > 0).")

    ev = [x["avg_r"] for x in (S, H) if x]
    if all(e > 0.15 for e in ev):
        verdict = "مثبت: هر دو آزمون میانگین R مثبت معنادار دارند. هنوز تضمین نیست؛ اندازه را کوچک نگه دارید."
    elif all(e < -0.05 for e in ev):
        verdict = "منفی: با این حد ضرر و هدف، این سهم در گذشته ضرر داده است. برنامه را عوض کنید یا وارد نشوید."
    else:
        verdict = "شیر یا خط: لبه‌ی روشنی دیده نمی‌شود. بدون دلیل دیگر (خبر، ورود پول) وارد نشوید."
    if H and H["n"] < 30:
        verdict += f" (توجه: تاریخچه فقط {H['n']} نمونه دارد؛ آماری ضعیف است.)"
    print(f"\n  حکم: {verdict}")
    out = {"symbol": plan["symbol"], "plan": {k: plan[k] for k in ("entry", "stop", "target")}, "hold": hold,
           "sims": a.sims, "days": len(rel), "monte_carlo": S, "history": H, "breakeven_winrate": be,
           "locked_down_share": locked, "verdict": verdict, "run_at": I.market_status(cfg)["now"]}
    I.write_json("timemachine.json", out)
    print(f"\nذخیره شد: {I.path('timemachine.json')}   بعدی: /iran-budget")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    c = sp.add_parser("run")
    c.add_argument("--sims", type=int, default=10000)
    c.add_argument("--days", type=int, default=250)
    c.add_argument("--hold", type=int)
    c.add_argument("--setup")
    c.add_argument("--seed", type=int, default=7)
    a = p.parse_args()
    cmd_run(a)


if __name__ == "__main__":
    I.run(main)
