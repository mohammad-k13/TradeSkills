"""iran-paper: a demo account with fake money on REAL TSETMC prices. Nothing goes to a broker.

  python paper.py reset [--cash 3500000]        # new account (Toman)
  python paper.py status                        # cash, equity, positions, open orders, stats
  python paper.py update                        # fill/expire orders and run stops/targets on real trades
  python paper.py buy SYMBOL QTY PRICE --stop S --target T [--no-risk]
  python paper.py sell SYMBOL [QTY] [PRICE] [--no-risk]
  python paper.py cancel ORDER_ID
  python paper.py history

How orders fill (all on real trades from TSETMC, fees included):
  * a BUY limit fills at the first real trade AFTER the order at or below your price
    (a SELL: at or above), at that trade's price;
  * placed while the stock is in a buy queue at your price, you stand BEHIND the queue: you fill
    only after as many shares as were ahead of you (plus yours) have traded at that price
    (same for a sell in a sell queue);
  * orders are good for one session; placed while the market is closed they wait for the next one;
  * with paper_auto_exits on, an open position is sold at the first real trade at/below its stop
    or at/above its target (the stop can fill worse than the stop price: gaps are real).
  * all-or-nothing fills (no partial fills).
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "iran-common"))
import iran as I  # noqa: E402

FILE = "paper.json"


# ---------------------------------------------------------------- state
def new_account(cash_toman: float) -> dict:
    c = cash_toman * 10
    return {"created": I.market_status()["now"], "start_cash_rial": c, "cash_rial": c, "next_id": 1,
            "orders": [], "positions": [], "trades": [], "equity": [], "last_equity_rial": c}


def load() -> dict:
    p = I.read_json(FILE)
    if p is None:
        p = new_account(I.config()["paper_start_cash_toman"])
        save(p)
    return p


def save(p):
    I.write_json(FILE, p)


def session_key(t: dt.datetime | None = None):
    """(date int, time int) the order counts from: now if the market is open, else the next session's open."""
    cfg = I.config()
    t = t or I.now_tehran()
    st = I.market_status(cfg, t)
    if st["open"]:
        return int(t.strftime("%Y%m%d")), int(t.strftime("%H%M%S"))
    d = I.next_session(cfg, t)
    return int(d.strftime("%Y%m%d")), 0


# ---------------------------------------------------------------- orders
def place(o: dict, source="manual") -> dict:
    """o: symbol, insCode, side, qty, price, [stop, target]. Returns the stored paper order."""
    cfg = I.config()
    p = load()
    fb, fs = I.fees(cfg)
    qty, price = int(o["qty"]), float(o["price"])
    if qty <= 0 or price <= 0:
        raise I.IranError("تعداد و قیمت باید مثبت باشند.")
    q = I.quote(o["insCode"])
    d, t = session_key()
    rec = {"id": p["next_id"], "symbol": o["symbol"], "insCode": o["insCode"], "side": o["side"], "qty": qty,
           "price": price, "stop": o.get("stop"), "target": o.get("target"), "status": "open", "source": source,
           "placed_at": I.market_status(cfg)["now"], "valid_date": d, "after_time": t, "queue_ahead": 0,
           "reserve_rial": 0, "ref_order": o.get("id")}
    if o["side"] == "buy":
        need = qty * price * (1 + fb)
        free = I.account_cash_rial(cfg)
        if need > free + 1:
            raise I.IranError(f"نقد آزاد کافی نیست: لازم {I.money(need, cfg)}، موجود {I.money(free, cfg)}.")
        rec["reserve_rial"] = round(need)
        if t and q["queue"] == "buy_queue" and price >= q["band_max"]:
            rec["queue_ahead"] = (q["book"][0].get("bid_vol") or 0) if q["book"] else 0
    else:
        pos = next((x for x in p["positions"] if x["insCode"] == o["insCode"]), None)
        held = pos["qty"] if pos else 0
        pend = sum(x["qty"] for x in p["orders"] if x["status"] == "open" and x["side"] == "sell" and x["insCode"] == o["insCode"])
        if qty > held - pend:
            raise I.IranError(f"فقط {held - pend:,} سهم {o['symbol']} برای فروش دارید.")
        if t and q["queue"] == "sell_queue" and price <= q["band_min"]:
            rec["queue_ahead"] = (q["book"][0].get("ask_vol") or 0) if q["book"] else 0
    p["next_id"] += 1
    p["orders"].append(rec)
    save(p)
    return rec


def cancel(oid: int) -> dict:
    p = load()
    o = next((x for x in p["orders"] if x["id"] == oid), None)
    if not o or o["status"] != "open":
        raise I.IranError(f"سفارش باز #{oid} پیدا نشد.")
    o["status"] = "cancelled"
    o["closed_at"] = I.market_status()["now"]
    save(p)
    return o


# ---------------------------------------------------------------- engine
def _fill_buy(p, o, px, when, fb, fs):
    cost = o["qty"] * px * (1 + fb)
    p["cash_rial"] -= cost
    o.update(status="filled", fill_price=px, filled_at=when, cost_rial=round(cost))
    pos = next((x for x in p["positions"] if x["insCode"] == o["insCode"]), None)
    risk_ps = (px * (1 + fb) - o["stop"] * (1 - fs)) if o.get("stop") else None
    if pos:
        tot = pos["qty"] + o["qty"]
        pos["avg_price"] = (pos["avg_price"] * pos["qty"] + px * o["qty"]) / tot
        pos["cost_rial"] += cost
        pos["qty"] = tot
        if risk_ps:
            pos["risk_rial"] = pos.get("risk_rial", 0) + o["qty"] * risk_ps
    else:
        p["positions"].append({"symbol": o["symbol"], "insCode": o["insCode"], "qty": o["qty"], "avg_price": px,
                               "cost_rial": cost, "stop": o.get("stop"), "target": o.get("target"),
                               "opened": when, "opened_key": [int(when[:10].replace("-", "")), int(when[11:].replace(":", "") + "00")],
                               "risk_rial": o["qty"] * risk_ps if risk_ps else None, "order_id": o["id"],
                               "checked_date": int(when[:10].replace("-", ""))})


def _sell(p, pos, qty, px, when, reason, fs):
    proceeds = qty * px * (1 - fs)
    part_cost = pos["cost_rial"] * qty / pos["qty"]
    pnl = proceeds - part_cost
    risk = (pos.get("risk_rial") or 0) * qty / pos["qty"]
    p["cash_rial"] += proceeds
    p["trades"].append({"symbol": pos["symbol"], "qty": qty, "buy": round(pos["avg_price"], 2), "sell": px,
                        "pnl_rial": round(pnl), "r": round(pnl / risk, 2) if risk else None,
                        "opened": pos["opened"], "closed": when, "reason": reason})
    pos["cost_rial"] -= part_cost
    if pos.get("risk_rial"):
        pos["risk_rial"] -= risk
    pos["qty"] -= qty
    if pos["qty"] <= 0:
        p["positions"].remove(pos)
    return pnl


def _hhmmss(n):
    s = f"{int(n):06d}"
    return f"{s[:2]}:{s[2:4]}"


def update(verbose=False) -> list[str]:
    """Process open orders and auto-exits against real trades. Returns plain-language events."""
    cfg = I.config()
    fb, fs = I.fees(cfg)
    p = load()
    now = I.now_tehran()
    today = int(now.strftime("%Y%m%d"))
    st = I.market_status(cfg)
    events = []
    trades_cache: dict[str, list] = {}
    quotes: dict[str, dict] = {}

    def trades(ins):
        if ins not in trades_cache:
            try:
                trades_cache[ins] = I.trades_today(ins)
            except I.IranError:
                trades_cache[ins] = []
        return trades_cache[ins]

    def quote(ins):
        if ins not in quotes:
            quotes[ins] = I.quote(ins)
        return quotes[ins]

    session_over = st["state"] == "closed" and now.time() >= I._hm(cfg["session_close"])

    def find_fill(o, trs):
        need = o["queue_ahead"] + o["qty"]
        cum = 0.0
        for t in trs:
            if t["time"] <= o["after_time"]:
                continue
            ok = t["price"] <= o["price"] if o["side"] == "buy" else t["price"] >= o["price"]
            if not ok:
                continue
            if not o["queue_ahead"] or t["price"] != o["price"]:
                return t            # no queue, or it traded through the queue price (queue gone)
            cum += t["qty"]
            if cum >= need:
                return t
        return None

    # ---- orders
    for o in [x for x in p["orders"] if x["status"] == "open"]:
        vd = o["valid_date"]
        if vd > today:
            continue                                   # waits for the next session
        if vd == today:
            q = quote(o["insCode"])
            if str(q["date"]) != str(today):           # no trade today yet (or holiday / halt)
                if session_over:
                    o["valid_date"], o["after_time"] = int(I.next_session(cfg).strftime("%Y%m%d")), 0
                continue
            trs = trades(o["insCode"])
        else:                                          # a past session the dashboard did not see
            try:
                trs = I.trades_on(o["insCode"], vd)
            except I.IranError:
                trs = []
            if not trs:
                o["valid_date"], o["after_time"] = int(I.next_session(cfg).strftime("%Y%m%d")), 0
                continue
        fill = find_fill(o, trs)
        if not fill:
            if vd < today or session_over:
                o.update(status="expired", closed_at=st["now"])
                events.append(f"سفارش #{o['id']} {o['symbol']} تا پایان جلسه پر نشد و منقضی شد.")
            continue
        if fill:
            d = str(vd)
            px = min(fill["price"], o["price"]) if o["side"] == "buy" else max(fill["price"], o["price"])
            when = f"{d[:4]}-{d[4:6]}-{d[6:]} {_hhmmss(fill['time'])}"
            if o["side"] == "buy":
                _fill_buy(p, o, px, when, fb, fs)
                events.append(f"✓ خرید #{o['id']} پر شد: {o['qty']:,} {o['symbol']} @ {I.price(px)} ({_hhmmss(fill['time'])})")
            else:
                pos = next((x for x in p["positions"] if x["insCode"] == o["insCode"]), None)
                if pos:
                    pnl = _sell(p, pos, min(o["qty"], pos["qty"]), px, when, "دستی", fs)
                    o.update(status="filled", fill_price=px, filled_at=when)
                    events.append(f"✓ فروش #{o['id']} پر شد: {o['qty']:,} {o['symbol']} @ {I.price(px)} — سود/زیان {I.money(pnl, cfg)}")
                else:
                    o.update(status="cancelled", closed_at=st["now"])

    # ---- auto exits (stop / target) on real trades
    if cfg.get("paper_auto_exits", True):
        for pos in list(p["positions"]):
            if any(x["status"] == "open" and x["side"] == "sell" and x["insCode"] == pos["insCode"] for x in p["orders"]):
                continue
            stop, target = pos.get("stop"), pos.get("target")
            if not stop and not target:
                continue
            hit = None
            # sessions between the last check and today: daily bars
            if pos.get("checked_date", today) < today:
                try:
                    for b in I.daily(pos["insCode"], days=30, adjust=False):
                        if pos["checked_date"] < b["date"] < today:
                            if stop and b["open"] <= stop:
                                hit = (b["open"], b["date"], "حد ضرر (گپ)")
                            elif stop and b["low"] <= stop:
                                hit = (stop, b["date"], "حد ضرر")
                            elif target and b["high"] >= target:
                                hit = (target, b["date"], "هدف")
                            if hit:
                                break
                except I.IranError:
                    pass
                if hit:
                    d = str(hit[1])
                    when = f"{d[:4]}-{d[4:6]}-{d[6:]} 12:30"
                    pnl = _sell(p, pos, pos["qty"], hit[0], when, hit[2], fs)
                    events.append(f"{'🔻' if 'ضرر' in hit[2] else '🎯'} {hit[2]} {pos['symbol']} @ {I.price(hit[0])} "
                                  f"({I.jdate(hit[1])}) — {I.money(pnl, cfg)}")
                    continue
            q = quote(pos["insCode"])
            if str(q["date"]) == str(today):
                start = pos["opened_key"][1] if pos["opened_key"][0] == today else 0
                for t in trades(pos["insCode"]):
                    if t["time"] <= start:
                        continue
                    if stop and t["price"] <= stop:
                        hit = (t["price"], t["time"], "حد ضرر")
                        break
                    if target and t["price"] >= target:
                        hit = (target, t["time"], "هدف")
                        break
                if hit:
                    when = f"{now.strftime('%Y-%m-%d')} {_hhmmss(hit[1])}"
                    pnl = _sell(p, pos, pos["qty"], hit[0], when, hit[2], fs)
                    events.append(f"{'🔻' if 'ضرر' in hit[2] else '🎯'} {hit[2]} {pos['symbol']} @ {I.price(hit[0])} "
                                  f"({_hhmmss(hit[1])}) — {I.money(pnl, cfg)}")
                    continue
            if pos in p["positions"] and session_over and str(q["date"]) == str(today):
                pos["checked_date"] = today     # today's trades were all checked

    # ---- equity snapshot
    eq = p["cash_rial"]
    for pos in p["positions"]:
        try:
            qq = quote(pos["insCode"])
            last = qq["last"] or pos["avg_price"]
            pos["chg_pct"], pos["queue"] = qq.get("chg_pct"), qq.get("queue")
        except I.IranError:
            last = pos["avg_price"]
        pos["last"] = last
        eq += pos["qty"] * last * (1 - fs)
    p["last_equity_rial"] = round(eq)
    stamp = st["now"]
    if not p["equity"] or p["equity"][-1]["t"][:15] != stamp[:15] or events:
        p["equity"].append({"t": stamp, "equity": round(eq)})
    else:
        p["equity"][-1] = {"t": stamp, "equity": round(eq)}
    # keep the curve light: one point per 10 minutes, all of them for the last 2 days
    if len(p["equity"]) > 3000:
        p["equity"] = p["equity"][::2]
    save(p)
    for e in events:
        I.write_json("paper_events.json", ((I.read_json("paper_events.json", []) or []) + [{"t": st["now"], "msg": e}])[-200:])
    return events


def stats(p) -> dict:
    tr = p["trades"]
    wins = [t for t in tr if t["pnl_rial"] > 0]
    losses = [t for t in tr if t["pnl_rial"] <= 0]
    gross_w = sum(t["pnl_rial"] for t in wins)
    gross_l = -sum(t["pnl_rial"] for t in losses)
    rs = [t["r"] for t in tr if t.get("r") is not None]
    peak, mdd = 0, 0
    for e in p["equity"]:
        peak = max(peak, e["equity"])
        if peak:
            mdd = max(mdd, (peak - e["equity"]) / peak)
    eq = p.get("last_equity_rial") or p["cash_rial"]
    return {"trades": len(tr), "wins": len(wins), "losses": len(losses),
            "win_rate": len(wins) / len(tr) if tr else None,
            "total_pnl_rial": sum(t["pnl_rial"] for t in tr), "profit_factor": gross_w / gross_l if gross_l else None,
            "avg_r": sum(rs) / len(rs) if rs else None, "max_drawdown": mdd,
            "equity_rial": eq, "return_pct": (eq / p["start_cash_rial"] - 1) * 100}


# ---------------------------------------------------------------- CLI
def cmd_status(a):
    cfg = I.config()
    ev = update()
    for e in ev:
        print(e)
    p = load()
    s = stats(p)
    print(f"■ حساب آزمایشی (از {p['created'][:10]})   ارزش: {I.money(s['equity_rial'], cfg)} ({s['return_pct']:+.2f}%)"
          f"   نقد آزاد: {I.money(I.account_cash_rial(cfg), cfg)}")
    fb, fs = I.fees(cfg)
    for x in p["positions"]:
        pnl = x["qty"] * x.get("last", x["avg_price"]) * (1 - fs) - x["cost_rial"]
        print(f"  {x['symbol']:<8} {x['qty']:>8,} × {I.price(x['avg_price'])} → {I.price(x.get('last'))}  "
              f"{I.money(pnl, cfg)}   حد ضرر {I.price(x.get('stop'))}  هدف {I.price(x.get('target'))}")
    for o in p["orders"]:
        if o["status"] == "open":
            wait = "" if o["valid_date"] <= int(I.now_tehran().strftime("%Y%m%d")) else "  (جلسه بعد)"
            q = f"  پشت صف {o['queue_ahead']:,.0f}" if o["queue_ahead"] else ""
            print(f"  سفارش #{o['id']} {'خرید' if o['side']=='buy' else 'فروش'} {o['qty']:,} {o['symbol']} @ {I.price(o['price'])}{q}{wait}")
    if s["trades"]:
        print(f"  معاملات بسته: {s['trades']}  برد {s['win_rate']*100:.0f}%  سود/زیان {I.money(s['total_pnl_rial'], cfg)}"
              + (f"  میانگین R {s['avg_r']:+.2f}" if s["avg_r"] is not None else "")
              + f"  بیشترین افت {s['max_drawdown']*100:.1f}%")


def _risk_gate(o, a):
    if a.no_risk:
        return
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "iran-risk"))
    import risk as R  # noqa: E402
    o["id"] = I.order_hash(o)
    r = R.check(o, I.config())
    for w in r["warnings"]:
        print(f"  ⚠ {w}")
    if r["verdict"] != "PASS":
        for b in r["blocks"]:
            print(f"  ✖ {b}")
        I.die("بررسی ریسک: BLOCK — سفارش آزمایشی هم ثبت نشد. (--no-risk برای نادیده گرفتن)")


def cmd_buy(a):
    info = I.resolve(a.symbol)
    o = {"symbol": info["symbol"], "insCode": info["insCode"], "side": "buy", "qty": a.qty, "price": a.price,
         "stop": a.stop, "target": a.target}
    _risk_gate(o, a)
    r = place(o)
    print(f"سفارش آزمایشی #{r['id']} ثبت شد: خرید {r['qty']:,} {r['symbol']} @ {I.price(r['price'])}"
          + (f" (پشت صف {r['queue_ahead']:,.0f} سهم)" if r["queue_ahead"] else "")
          + (" — برای جلسه بعد" if r["after_time"] == 0 else ""))


def cmd_sell(a):
    info = I.resolve(a.symbol)
    p = load()
    pos = next((x for x in p["positions"] if x["insCode"] == info["insCode"]), None)
    if not pos:
        I.die(f"{info['symbol']} در حساب آزمایشی نیست.")
    q = I.quote(info["insCode"])
    px = a.price or (q["book"][0]["bid"] if q["book"] and q["book"][0]["bid"] else q["last"])
    o = {"symbol": info["symbol"], "insCode": info["insCode"], "side": "sell", "qty": a.qty or pos["qty"], "price": px}
    _risk_gate(o, a)
    r = place(o)
    print(f"سفارش آزمایشی #{r['id']} ثبت شد: فروش {r['qty']:,} {r['symbol']} @ {I.price(r['price'])}")


def main():
    pr = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = pr.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("reset")
    r.add_argument("--cash", type=float)
    sp.add_parser("status")
    sp.add_parser("update")
    b = sp.add_parser("buy")
    b.add_argument("symbol")
    b.add_argument("qty", type=int)
    b.add_argument("price", type=float)
    b.add_argument("--stop", type=float)
    b.add_argument("--target", type=float)
    b.add_argument("--no-risk", action="store_true")
    s = sp.add_parser("sell")
    s.add_argument("symbol")
    s.add_argument("qty", type=int, nargs="?")
    s.add_argument("price", type=float, nargs="?")
    s.add_argument("--no-risk", action="store_true")
    c = sp.add_parser("cancel")
    c.add_argument("id", type=int)
    sp.add_parser("history")
    a = pr.parse_args()
    if a.cmd == "reset":
        cash = a.cash or I.config()["paper_start_cash_toman"]
        save(new_account(cash))
        I.write_json("paper_events.json", [])
        print(f"حساب آزمایشی تازه با {I.money(cash * 10)} ساخته شد.")
    elif a.cmd == "status":
        cmd_status(a)
    elif a.cmd == "update":
        for e in update() or ["تغییری نبود."]:
            print(e)
    elif a.cmd == "buy":
        cmd_buy(a)
    elif a.cmd == "sell":
        cmd_sell(a)
    elif a.cmd == "cancel":
        o = cancel(a.id)
        print(f"سفارش #{o['id']} لغو شد.")
    else:
        p = load()
        for t in p["trades"]:
            print(f"{t['closed'][:16]}  {t['symbol']:<8} {t['qty']:>8,}  {I.price(t['buy'])} → {I.price(t['sell'])}  "
                  f"{I.money(t['pnl_rial'])}  R={t['r']}  ({t['reason']})")


if __name__ == "__main__":
    I.run(main)
