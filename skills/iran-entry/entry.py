"""iran-entry: watch a setup bar by bar and say the moment to get in. Long only. Never places orders.

  python entry.py check SYMBOL [--level PRICE] [--bar 5] [--or 15] [--vol 1.5] [--date 20261108]
  python entry.py watchlist [--bar 5] [--or 15]     # check every symbol in trader/watchlist.json (top 10)

Rule (default): build the opening range (first --or minutes after 09:00), then the entry is the
first COMPLETED bar whose close is above the range high (or above --level, e.g. a 20-day high).
--vol 1.5: that bar's volume must be >= 1.5x the average bar so far.

Iran-specific states
  queue_locked   the stock is in a buy queue at the upper limit: the price cannot go higher today,
                 so a breakout cannot trigger; a buy order only joins the queue (may never fill).
  level_above_band  your level is above today's upper limit: impossible today.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "iran-common"))
import iran as I  # noqa: E402


def evaluate(sym: str, a, cfg) -> dict:
    info = I.resolve(sym)
    ins = info["insCode"]
    st = I.market_status(cfg)
    q = I.quote(ins)
    today = I.now_tehran().strftime("%Y%m%d")
    replay = bool(a.date)
    trades = I.trades_on(ins, int(a.date)) if replay else I.trades_today(ins)
    bars = I.bars_from_trades(trades, a.bar, cfg["session_open"])
    now = I.now_tehran()
    res = {"symbol": info["symbol"], "insCode": ins, "checked_at": st["now"], "bar_minutes": a.bar,
           "or_minutes": a.or_, "band_min": q["band_min"], "band_max": q["band_max"],
           "last": q["last"], "yesterday": q["yesterday"], "queue": q["queue"], "replay_date": a.date}
    if replay:
        day = [b for b in I.daily(ins, days=0, adjust=False) if str(b["date"]) == str(a.date)]
        if not day:
            raise I.IranError(f"{info['symbol']} در تاریخ {a.date} معامله نداشته است.")
        bp = float(cfg.get("band_pct", 0.03))   # replay: the band of that day is approximated
        y = day[0]["yesterday"]
        res["band_note"] = "approximate (±%.0f%% of that day's reference price)" % (bp * 100)
        q = dict(q, band_max=I.round_tick(y * (1 + bp), cfg), band_min=I.round_tick(y * (1 - bp), cfg, down=False),
                 yesterday=y, last=day[0]["last"], queue="")
        res.update(band_min=q["band_min"], band_max=q["band_max"], yesterday=y, last=q["last"], queue="")

    if not replay and q["date"] and str(q["date"]) != today and not st["open"]:
        res.update(state="not_open", say=f"بازار امروز باز نشده/معامله‌ای نیست ({st['reason']}). آخرین معامله: {I.jdate(q['date'])}")
        return res
    if not replay and st["state"] == "pre_open":
        res.update(state="not_open", say=f"هنوز باز نشده: {st['reason']}")
        return res
    if q["state_code"] and q["state_code"] != "A" and not replay:
        res.update(state="halted", say=f"نماد مجاز نیست: {q['state']}")
        return res
    if not bars:
        res.update(state="waiting", say="هنوز معامله‌ای ثبت نشده.")
        return res

    n_or = max(1, a.or_ // a.bar)
    # a bar is complete when its end time has passed (or we are replaying a past day)
    def complete(b):
        if replay or not st["open"]:
            return True
        h, m = map(int, b["start"].split(":"))
        end = dt.datetime.combine(now.date(), dt.time(h, m), I.TEHRAN) + dt.timedelta(minutes=a.bar)
        return now >= end

    done = [b for b in bars if complete(b)]
    or_bars = done[:n_or]
    if len(or_bars) < n_or:
        res.update(state="building_range", say=f"دامنه آغازین {a.or_} دقیقه هنوز کامل نشده ({len(or_bars)}/{n_or} کندل).")
        return res
    or_hi = max(b["high"] for b in or_bars)
    or_lo = min(b["low"] for b in or_bars)
    level = a.level or or_hi
    res.update(or_high=or_hi, or_low=or_lo, or_mid=round((or_hi + or_lo) / 2, 1), level=level,
               level_source="--level" if a.level else "opening range high")

    band_max = q["band_max"]
    if level >= band_max and band_max:
        res.update(state="level_above_band",
                   say=f"سطح {I.price(level)} برابر/بالاتر از سقف مجاز امروز ({I.price(band_max)}) است؛ امروز شکست ممکن نیست.")
        if q["queue"] == "buy_queue":
            res["state"] = "queue_locked"
            res["say"] += " نماد در صف خرید است؛ سفارش خرید فقط به ته صف اضافه می‌شود."
        return res

    after = done[n_or:]
    vols = [b["volume"] for b in done]
    for i, b in enumerate(after):
        if b["close"] > level:
            avg = sum(vols[: n_or + i]) / max(1, n_or + i)
            if a.vol and avg and b["volume"] < a.vol * avg:
                continue
            res.update(state="triggered", trigger_time=b["start"], trigger_bar=b, entry=b["close"],
                       say=f"ورود فعال شد: کندل {b['start']} با {I.price(b['close'])} بالای {I.price(level)} بسته شد.")
            if b["close"] >= band_max:
                res["warning"] = "قیمت ورود روی سقف مجاز است؛ احتمال صف خرید و پر نشدن سفارش."
            return res

    cutoff = cfg["entry_window"][1]
    if (not replay and st["open"] and not st["in_entry_window"]) or replay or not st["open"]:
        if not replay and st["open"]:
            res.update(state="expired", say=f"پنجره ورود ({cutoff}) تمام شد و شکستی رخ نداد.")
        else:
            res.update(state="expired", say="جلسه تمام شد و شکستی رخ نداد.")
        return res
    last = done[-1]["close"] if done else q["last"]
    gap = (level / last - 1) * 100 if last else None
    res.update(state="waiting", distance_pct=round(gap, 2) if gap is not None else None,
               say=f"منتظر: آخرین {I.price(last)}، سطح {I.price(level)} ({gap:+.2f}% فاصله).")
    if q["queue"] == "sell_queue":
        res["warning"] = "نماد در صف فروش است."
    return res


def show(r):
    print(f"■ {r['symbol']}  [{r['state']}]  {r['say']}")
    if "or_high" in r:
        print(f"   دامنه آغازین: {I.price(r['or_low'])} – {I.price(r['or_high'])} (میانه {I.price(r['or_mid'])})"
              f"   دامنه مجاز امروز: {I.price(r['band_min'])} – {I.price(r['band_max'])}")
    if r.get("warning"):
        print(f"   ⚠ {r['warning']}")


def cmd_check(a):
    cfg = I.config()
    r = evaluate(a.symbol, a, cfg)
    show(r)
    allr = I.read_json("entry.json", {}) or {}
    allr.setdefault("symbols", {})[r["symbol"]] = r
    allr["last"] = r["symbol"]
    I.write_json("entry.json", allr)
    if r["state"] == "triggered":
        print("\nبعدی: /iran-exit برای تعیین حد ضرر و هدف.")


def cmd_watch(a):
    cfg = I.config()
    w = I.read_json("watchlist.json", {}) or {}
    syms = list(dict.fromkeys(w.get("manual", []) + [s["symbol"] for s in (w.get("symbols") or [])[: a.top]]))
    if not syms:
        I.die("واچ‌لیست خالی است.")
    allr = I.read_json("entry.json", {}) or {}
    allr.setdefault("symbols", {})
    for s in syms:
        a.level = None
        for row in w.get("symbols") or []:
            if row["symbol"] == s and "breakout20" in row.get("setups", []) and a.use_high20:
                a.level = (row.get("metrics") or {}).get("high20")
        try:
            r = evaluate(s, a, cfg)
        except I.IranError as e:
            print(f"■ {s}: {e}")
            continue
        show(r)
        allr["symbols"][r["symbol"]] = r
    I.write_json("entry.json", allr)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    for name in ("check", "watchlist"):
        c = sp.add_parser(name)
        if name == "check":
            c.add_argument("symbol")
            c.add_argument("--level", type=float)
        else:
            c.add_argument("--top", type=int, default=10)
            c.add_argument("--use-high20", action="store_true")
        c.add_argument("--bar", type=int, default=5)
        c.add_argument("--or", dest="or_", type=int, default=15)
        c.add_argument("--vol", type=float, default=0)
        c.add_argument("--date", help="replay a past session, e.g. 20261108")
    a = p.parse_args()
    (cmd_check if a.cmd == "check" else cmd_watch)(a)


if __name__ == "__main__":
    I.run(main)
