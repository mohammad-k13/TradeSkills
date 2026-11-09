"""iran-scanner: scan every TSE / Fara Bourse share for setups and write trader/watchlist.json.

  python scanner.py scan [--setups a,b] [--min-value TOMAN] [--top N] [--no-daily] [--limit 30]
  python scanner.py show                       # print the last watchlist
  python scanner.py add SYMBOL [SYMBOL...]     # add symbols to the watchlist by hand
  python scanner.py remove SYMBOL [...]

Setups
  live (one market-watch request, works during and after the session):
    buy_queue      closing/last at the upper limit, sell side empty (صف خرید)
    sell_queue     at the lower limit, buy side empty (صف فروش)            [warning list]
    smart_money    real (حقیقی) net inflow >= 1 billion toman and buyer power >= 1.5
    real_power     buyer power (سرانه خرید/سرانه فروش حقیقی) >= 2
  daily (history for the most-traded --top symbols, cached per day):
    volume_spike   today's volume >= 2x the 20-day average
    breakout20     close above the highest close of the previous 20 sessions
    reclaim_ma20   close back above the 20-day average after closing below it
    oversold       RSI(14) <= 30
    bounce         RSI was <= 30 in the last 3 sessions and today closed up
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "iran-common"))
import iran as I  # noqa: E402

LIVE = ["buy_queue", "sell_queue", "smart_money", "real_power"]
DAILY = ["volume_spike", "breakout20", "reclaim_ma20", "oversold", "bounce"]


def live_rows(cfg):
    mw = I.market_watch()
    ct = I.client_type_all()
    rows = []
    for x in mw:
        sym = x.get("lva")
        if not I.is_share(sym, int(x.get("yVal") or 0), cfg):
            continue
        last, close, y = float(x.get("pdv") or 0), float(x.get("pcl") or 0), float(x.get("py") or 0)
        bl = (x.get("blDs") or [{}])[0]
        r = {"insCode": x["insCode"], "symbol": I.fa(sym), "name": I.fa(x.get("lvc")), "yVal": x.get("yVal"),
             "last": last, "close": close, "yesterday": y, "high": float(x.get("pmx") or 0),
             "low": float(x.get("pmn") or 0), "band_max": float(x.get("pMax") or 0),
             "band_min": float(x.get("pMin") or 0), "volume": float(x.get("qtj") or 0),
             "value": float(x.get("qtc") or 0), "trades": int(x.get("ztt") or 0),
             "eps": x.get("eps"), "pe": x.get("pe"), "time": x.get("hEven"),
             "book": [{"bid": bl.get("pmd"), "bid_vol": bl.get("qmd"), "ask": bl.get("pmo"), "ask_vol": bl.get("qmo")}]}
        r["chg_pct"] = I.pct(last, y)
        r["close_pct"] = I.pct(close, y)
        r["queue"] = I.queue_state(r)
        if r["queue"] == "buy_queue":
            r["queue_value"] = (bl.get("qmd") or 0) * r["band_max"]
        elif r["queue"] == "sell_queue":
            r["queue_value"] = (bl.get("qmo") or 0) * r["band_min"]
        r["flow"] = I.flow_metrics(ct.get(x["insCode"], {}), close or last)
        rows.append(r)
    names = {I.norm(r["symbol"]) for r in rows}
    if not cfg.get("allow_rights"):
        rows = [r for r in rows if not (I.norm(r["symbol"]).endswith("ح") and I.norm(r["symbol"])[:-1] in names)]
    return rows


def live_setups(r):
    s = []
    f = r["flow"]
    if r["queue"] == "buy_queue":
        s.append("buy_queue")
    if r["queue"] == "sell_queue":
        s.append("sell_queue")
    nv = f.get("real_net_value") or 0
    if nv >= 1e10 and (f.get("real_power") or 0) >= 1.5:          # 1 billion toman
        s.append("smart_money")
    if (f.get("real_power") or 0) >= 2:
        s.append("real_power")
    return s


def daily_setups(r, bars):
    """bars: adjusted daily history (excludes today); r: today's live row."""
    s, m = [], {}
    if len(bars) < 21 or not r["close"]:
        return s, m
    closes = [b["close"] for b in bars]
    today_close = r["close"]
    all_c = closes + [today_close]
    vols = [b["volume"] for b in bars[-20:]]
    avg_v = sum(vols) / len(vols) if vols else 0
    m["vol_ratio"] = round(r["volume"] / avg_v, 2) if avg_v else None
    m["high20"] = max(closes[-20:])
    m["ma20"] = round(sum(all_c[-20:]) / 20, 1)
    m["rsi14"] = I.rsi(all_c)
    prev_rsi = [I.rsi(all_c[:-k]) for k in (1, 2, 3)]
    if m["vol_ratio"] and m["vol_ratio"] >= 2:
        s.append("volume_spike")
    if today_close > m["high20"]:
        s.append("breakout20")
    prev_ma = sum(closes[-20:]) / 20
    if closes[-1] < prev_ma and today_close > m["ma20"]:
        s.append("reclaim_ma20")
    if m["rsi14"] is not None and m["rsi14"] <= 30:
        s.append("oversold")
    if any(p is not None and p <= 30 for p in prev_rsi) and today_close > closes[-1]:
        s.append("bounce")
    return s, m


def score(r):
    """Rank: setups first, then real money inflow, then value traded."""
    return (len([x for x in r["setups"] if x != "sell_queue"]), r["flow"].get("real_net_value") or 0, r["value"])


def cmd_scan(a):
    cfg = I.config()
    want = set((a.setups or ",".join(LIVE + DAILY)).split(","))
    bad = want - set(LIVE + DAILY)
    if bad:
        I.die(f"unknown setup(s): {', '.join(sorted(bad))}. Known: {', '.join(LIVE + DAILY)}")
    st = I.market_status(cfg)
    min_val = (a.min_value if a.min_value is not None else cfg["scan_min_value_toman"]) * 10
    rows = live_rows(cfg)
    traded = [r for r in rows if r["trades"] > 0]
    liquid = [r for r in traded if r["value"] >= min_val]
    print(f"دیده‌بان: {len(rows)} سهم، {len(traded)} معامله‌شده، {len(liquid)} با ارزش معاملات ≥ {I.money(min_val, cfg)}"
          f"  |  {st['jalali']}  ({st['reason']})")
    for r in liquid:
        r["setups"] = live_setups(r)
        r["metrics"] = {}
    need_daily = bool(want & set(DAILY)) and not a.no_daily
    if need_daily:
        top = sorted(liquid, key=lambda r: -r["value"])[: (a.top or cfg["scan_daily_top"])]
        print(f"تاریخچه روزانه برای {len(top)} نماد پرمعامله…", flush=True)
        for i, r in enumerate(top, 1):
            try:
                bars = I.daily(r["insCode"], days=60)
                if bars and str(bars[-1]["date"]) == I.now_tehran().strftime("%Y%m%d"):
                    bars = bars[:-1]
                s, m = daily_setups(r, bars)
                r["setups"] += s
                r["metrics"] = m
            except I.IranError as e:
                r["metrics"] = {"error": str(e)}
            if i % 25 == 0:
                print(f"  {i}/{len(top)}", flush=True)
            time.sleep(0.05)
    hits = [r for r in liquid if set(r["setups"]) & want]
    hits.sort(key=score, reverse=True)
    out = {"scanned_at": st["now"], "jalali": st["jalali"], "market": st["state"],
           "setups": sorted(want), "min_value_rial": min_val, "count": len(hits),
           "symbols": [{k: r[k] for k in ("symbol", "insCode", "name", "setups", "last", "close", "yesterday",
                                         "chg_pct", "close_pct", "band_min", "band_max", "queue", "value",
                                         "volume", "metrics")} | {"real_power": r["flow"].get("real_power"),
                                                                  "real_net_value": r["flow"].get("real_net_value"),
                                                                  "queue_value": r.get("queue_value")}
                       for r in hits]}
    manual = (I.read_json("watchlist.json", {}) or {}).get("manual", [])
    out["manual"] = manual
    I.write_json("watchlist.json", out)
    print_table(out, a.limit, cfg)


def print_table(w, limit, cfg):
    rows = w["symbols"][:limit]
    if not rows:
        print("هیچ نمادی با این فیلترها پیدا نشد.")
    else:
        print(f"\n{'نماد':<10} {'پایانی':>9} {'%':>6} {'ارزش':>22} {'قدرت':>5} {'ورود حقیقی':>22}  ستاپ‌ها")
        for r in rows:
            print(f"{r['symbol']:<10} {I.price(r['close'] or r['last']):>9} {r['close_pct'] if r['close_pct'] is not None else '-':>6} "
                  f"{I.money(r['value'], cfg):>22} {r['real_power'] or '-':>5} {I.money(r['real_net_value'], cfg):>22}  "
                  f"{', '.join(r['setups'])}")
        if len(w["symbols"]) > limit:
            print(f"… و {len(w['symbols']) - limit} نماد دیگر در trader/watchlist.json")
    if w.get("manual"):
        print("دستی: " + "، ".join(w["manual"]))
    print(f"\nذخیره شد: {I.path('watchlist.json')}")


def cmd_show(a):
    w = I.read_json("watchlist.json")
    if not w:
        I.die("هنوز واچ‌لیستی نیست. اول scan بزنید.")
    print(f"آخرین اسکن: {w.get('jalali')}  ({w.get('count')} نماد)")
    print_table(w, a.limit, I.config())


def cmd_add(a, remove=False):
    w = I.read_json("watchlist.json", {}) or {"symbols": []}
    man = w.get("manual", [])
    for s in a.symbols:
        info = I.resolve(s)
        if remove:
            man = [m for m in man if I.norm(m) != I.norm(info["symbol"])]
        elif info["symbol"] not in man:
            man.append(info["symbol"])
    w["manual"] = man
    I.write_json("watchlist.json", w)
    print("واچ‌لیست دستی: " + ("، ".join(man) or "(خالی)"))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("scan")
    s.add_argument("--setups")
    s.add_argument("--min-value", type=float, help="min value traded, TOMAN")
    s.add_argument("--top", type=int)
    s.add_argument("--no-daily", action="store_true")
    s.add_argument("--limit", type=int, default=30)
    s2 = sp.add_parser("show")
    s2.add_argument("--limit", type=int, default=30)
    s3 = sp.add_parser("add")
    s3.add_argument("symbols", nargs="+")
    s4 = sp.add_parser("remove")
    s4.add_argument("symbols", nargs="+")
    a = p.parse_args()
    if a.cmd == "scan":
        cmd_scan(a)
    elif a.cmd == "show":
        cmd_show(a)
    elif a.cmd == "add":
        cmd_add(a)
    else:
        cmd_add(a, remove=True)


if __name__ == "__main__":
    I.run(main)
