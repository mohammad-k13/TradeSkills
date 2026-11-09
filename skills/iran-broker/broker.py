"""iran-broker: turn a PASSED order into a ticket, record your yes word for word, track fills.
The order itself is entered on your broker's site (EasyTrader by default) through Chrome; this
script never talks to the broker. See SKILL.md for the browser steps.

  python broker.py ticket                     # show the pending order as a ticket (needs a fresh PASS)
  python broker.py confirm --said "بله بفرست"  # record your yes, verbatim (needs the ticket shown first)
  python broker.py sent [--note "..."]        # record that the order was submitted on the site
  python broker.py cancel [--note "..."]      # drop the pending order
  python broker.py fill --qty N --price P     # record what actually filled (from the site's orders tab)
  python broker.py close SYMBOL [--qty N] [--price P]   # build the SELL order that closes a position
  python broker.py positions                  # open positions with live P/L, stop and target
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "iran-common"))
import iran as I  # noqa: E402

FRESH_MIN = 10
YES = re.compile(r"^\s*(بله|آره|اره|اوکی|باشه|بفرست|ارسال کن|تایید|تأیید|yes|y|ok|okay|go|send( it)?)\b", re.I)


def pending():
    ords = I.read_json("orders.json", {}) or {}
    o = ords.get("pending")
    if not o:
        I.die("سفارش پیش‌نویسی نیست. مسیر: /iran-budget → /iran-risk → /iran-broker")
    return ords, o


def require_pass(o):
    if os.environ.get("IRAN_TRADER_NOW"):
        I.die("ساعت آزمایشی (IRAN_TRADER_NOW) فعال است؛ با ساعت آزمایشی سفارش واقعی ممنوع است.")
    r = o.get("risk") or {}
    if r.get("verdict") != "PASS":
        I.die("این سفارش از /iran-risk رد نشده (PASS ندارد). اول risk.py check.")
    if r.get("id") != I.order_hash(o):
        I.die("سفارش بعد از بررسی ریسک تغییر کرده است. دوباره risk.py check.")
    t = dt.datetime.strptime(r["checked_at"], "%Y-%m-%d %H:%M").replace(tzinfo=I.TEHRAN)
    age = (I.now_tehran() - t).total_seconds() / 60
    if age > FRESH_MIN:
        I.die(f"بررسی ریسک {age:.0f} دقیقه پیش بوده (بیش از {FRESH_MIN}). دوباره risk.py check.")


def log(event: str, o: dict, **kw):
    b = I.read_json("broker_log.json", []) or []
    b.append({"at": I.market_status()["now"], "event": event, "order_id": o.get("id"), "symbol": o.get("symbol"),
              "side": o.get("side"), "qty": o.get("qty"), "price": o.get("price")} | kw)
    I.write_json("broker_log.json", b)


def cmd_ticket(a):
    cfg = I.config()
    ords, o = pending()
    require_pass(o)
    side = "خرید" if o["side"] == "buy" else "فروش"
    print("┌──────────── بلیت سفارش ────────────")
    if I.is_paper(cfg):
        print("│ 🧪 حالت آزمایشی (پول مجازی، قیمت واقعی) — به کارگزاری نمی‌رود")
    else:
        print(f"│ کارگزاری:  {cfg.get('broker_name')}  {cfg.get('broker_url')}")
    print(f"│ نماد:      {o['symbol']}")
    print(f"│ سمت:       {side}")
    print(f"│ تعداد:     {o['qty']:,} سهم")
    print(f"│ قیمت:      {I.price(o['price'])} ریال  (محدود)")
    print(f"│ اعتبار:    روز")
    if o["side"] == "buy":
        print(f"│ ارزش تقریبی: {I.money(o.get('est_cost_rial'), cfg)} با کارمزد")
        print(f"│ حد ضرر:    {I.price(o['stop'])}  → ضرر {I.money(o.get('max_loss_rial'), cfg)}")
        print(f"│ هدف:       {I.price(o['target'])}  → سود {I.money(o.get('est_reward_rial'), cfg)}")
    print(f"│ بررسی ریسک: PASS  ({o['risk']['checked_at'][-5:]})   شناسه {o['id']}")
    print("└────────────────────────────────────")
    print("حد ضرر و هدف در ایزی‌تریدر خودکار ثبت نمی‌شوند؛ بعد از خرید، هشدارشان را با /iran-alerts بگذارید.")
    o["ticket_shown_at"] = I.market_status(cfg)["now"]
    I.write_json("orders.json", ords)
    log("ticket_shown", o)


def cmd_confirm(a):
    ords, o = pending()
    require_pass(o)
    if not o.get("ticket_shown_at"):
        I.die("اول بلیت را نشان بدهید (broker.py ticket).")
    if not YES.search(a.said or ""):
        I.die(f"«{a.said}» تایید روشن نیست. فقط با «بله» یا «بفرست» صریح ادامه می‌دهیم.")
    o["approved"] = {"said": a.said, "at": I.market_status()["now"]}
    I.write_json("orders.json", ords)
    log("user_approved", o, said=a.said)
    print(f"تایید ثبت شد: «{a.said}». حالا فرم سفارش در ایزی‌تریدر پر می‌شود؛ ارسال نهایی با شماست "
          f"(یا با یک «بله» دوم پس از دیدن فرم پرشده).")


def cmd_sent(a):
    cfg = I.config()
    ords, o = pending()
    require_pass(o)
    if not o.get("approved"):
        I.die("تایید کاربر ثبت نشده (broker.py confirm --said ...).")
    if I.is_paper(cfg):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "iran-paper"))
        import paper as P  # noqa: E402
        r = P.place(o, source="broker")
        o["status"] = "sent_paper"
        o["paper_id"] = r["id"]
        ords.setdefault("sent", []).append(o)
        ords["pending"] = None
        I.write_json("orders.json", ords)
        log("sent_paper", o, paper_id=r["id"])
        print(f"🧪 حالت آزمایشی: سفارش #{r['id']} در حساب آزمایشی ثبت شد (به کارگزاری نرفت)."
              + (f" پشت صف {r['queue_ahead']:,.0f} سهم." if r["queue_ahead"] else "")
              + (" برای جلسه بعد." if r["after_time"] == 0 else "")
              + " پر شدن با معاملات واقعی TSETMC بررسی می‌شود (paper.py status یا داشبورد).")
        return
    j = I.read_json("journal.json", {}) or {}
    day = j.setdefault("days", {}).setdefault(I.today_key(), {"orders": [], "risk_rial": 0, "entries": 0})
    rec = {k: o.get(k) for k in ("id", "symbol", "insCode", "side", "qty", "price", "stop", "target")}
    rec.update(time=I.market_status(cfg)["now"][-5:], risk_rial=o.get("max_loss_rial", 0) if o["side"] == "buy" else 0,
               said=o["approved"]["said"], note=a.note)
    day["orders"].append(rec)
    if o["side"] == "buy":
        day["entries"] += 1
        day["risk_rial"] += o.get("max_loss_rial", 0)
    I.write_json("journal.json", j)
    o["status"] = "sent"
    ords.setdefault("sent", []).append(o)
    ords["pending"] = None
    I.write_json("orders.json", ords)
    log("sent", o, note=a.note)
    print(f"ثبت شد: سفارش {o['id']} ارسال شد. وقتی پر شد: broker.py fill --qty ... --price ...")


def cmd_cancel(a):
    ords, o = pending()
    ords["pending"] = None
    I.write_json("orders.json", ords)
    log("cancelled", o, note=a.note)
    print("سفارش پیش‌نویس حذف شد.")


def last_sent(symbol=None):
    ords = I.read_json("orders.json", {}) or {}
    for o in reversed(ords.get("sent", [])):
        if not symbol or I.norm(o["symbol"]) == I.norm(symbol):
            return o
    return None


def cmd_fill(a):
    o = last_sent(a.symbol)
    if not o:
        I.die("سفارش ارسال‌شده‌ای پیدا نشد.")
    pos = I.read_json("positions.json", {"open": [], "closed": []}) or {"open": [], "closed": []}
    fb, fs = I.fees()
    if o["side"] == "buy":
        p = next((p for p in pos["open"] if p["symbol"] == o["symbol"]), None)
        if p:
            tot = p["qty"] + a.qty
            p["avg_price"] = (p["avg_price"] * p["qty"] + a.price * a.qty) / tot
            p["qty"] = tot
        else:
            pos["open"].append({"symbol": o["symbol"], "insCode": o["insCode"], "qty": a.qty, "avg_price": a.price,
                                "stop": o.get("stop"), "target": o.get("target"), "opened": I.today_key(),
                                "order_id": o["id"]})
    else:
        p = next((p for p in pos["open"] if p["symbol"] == o["symbol"]), None)
        if not p:
            I.die(f"موقعیت باز {o['symbol']} پیدا نشد.")
        sold = min(a.qty, p["qty"])
        pnl = sold * (a.price * (1 - fs) - p["avg_price"] * (1 + fb))
        pos["closed"].append({"symbol": p["symbol"], "qty": sold, "buy": p["avg_price"], "sell": a.price,
                              "opened": p["opened"], "closed": I.today_key(), "pnl_rial": round(pnl)})
        p["qty"] -= sold
        if p["qty"] <= 0:
            pos["open"].remove(p)
        print(f"سود/زیان خالص: {I.money(pnl)}")
    I.write_json("positions.json", pos)
    log("fill", o, fill_qty=a.qty, fill_price=a.price)
    print(f"پر شد: {o['side']} {a.qty:,} {o['symbol']} @ {I.price(a.price)}")


def cmd_close(a):
    cfg = I.config()
    pos = I.open_positions(cfg)
    info = I.resolve(a.symbol)
    p = next((p for p in pos if I.norm(p["symbol"]) == I.norm(info["symbol"])), None)
    qty = a.qty or (p["qty"] if p else None)
    if not qty:
        I.die(f"موقعیت باز {info['symbol']} ثبت نشده؛ --qty بدهید.")
    q = I.quote(info["insCode"])
    px = a.price or (q["band_min"] if q["queue"] == "sell_queue" else (q["book"][0]["bid"] if q["book"] and q["book"][0]["bid"] else q["last"]))
    o = {"symbol": info["symbol"], "insCode": info["insCode"], "side": "sell", "qty": int(qty), "price": px,
         "type": "limit", "validity": "day", "created_at": I.market_status(cfg)["now"], "status": "draft"}
    o["id"] = I.order_hash(o)
    ords = I.read_json("orders.json", {}) or {}
    ords["pending"] = o
    I.write_json("orders.json", ords)
    print(f"سفارش فروش پیش‌نویس: {qty:,} {info['symbol']} @ {I.price(px)} "
          f"({'کف دامنه، صف فروش' if q['queue']=='sell_queue' else 'بهترین مظنه خرید'}). بعدی: risk.py check")


def cmd_positions(a):
    cfg = I.config()
    if I.is_paper(cfg):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "iran-paper"))
        import paper as P  # noqa: E402
        P.cmd_status(a)
        return
    pos = (I.read_json("positions.json", {}) or {}).get("open", [])
    if not pos:
        print("موقعیت بازی ثبت نشده.")
        return
    fb, fs = I.fees(cfg)
    tot = 0
    for p in pos:
        q = I.quote(p["insCode"])
        pnl = p["qty"] * (q["last"] * (1 - fs) - p["avg_price"] * (1 + fb))
        tot += pnl
        flag = ""
        if p.get("stop") and q["last"] <= p["stop"]:
            flag = "  ⚠ زیر حد ضرر!"
        elif p.get("target") and q["last"] >= p["target"]:
            flag = "  ★ به هدف رسید"
        print(f"{p['symbol']:<8} {p['qty']:>10,} × {I.price(p['avg_price'])} → {I.price(q['last'])} "
              f"({q['chg_pct']:+}% امروز)  سود/زیان خالص {I.money(pnl, cfg)}  حد ضرر {I.price(p.get('stop'))} "
              f"هدف {I.price(p.get('target'))}{flag}{'  [صف فروش]' if q['queue']=='sell_queue' else ''}")
    print(f"\nجمع: {I.money(tot, cfg)}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    sp.add_parser("ticket")
    c = sp.add_parser("confirm")
    c.add_argument("--said", required=True)
    for n in ("sent", "cancel"):
        s = sp.add_parser(n)
        s.add_argument("--note")
    f = sp.add_parser("fill")
    f.add_argument("--qty", type=int, required=True)
    f.add_argument("--price", type=float, required=True)
    f.add_argument("--symbol")
    cl = sp.add_parser("close")
    cl.add_argument("symbol")
    cl.add_argument("--qty", type=int)
    cl.add_argument("--price", type=float)
    sp.add_parser("positions")
    a = p.parse_args()
    {"ticket": cmd_ticket, "confirm": cmd_confirm, "sent": cmd_sent, "cancel": cmd_cancel, "fill": cmd_fill,
     "close": cmd_close, "positions": cmd_positions}[a.cmd](a)


if __name__ == "__main__":
    I.run(main)
