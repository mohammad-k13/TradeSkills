"""iran-risk: check the pending order against every limit. PASS or BLOCK, before any broker step.

  python risk.py check              # the pending order in trader/orders.json
  python risk.py today              # risk used today, trades, orders
  python risk.py log [--days 3]

BUY orders are blocked when any of these fail:
  malformed order, stop missing / not below price, target not above price,
  blocked symbol, symbol not «مجاز» (halted / suspended), base market / rights / under-supervision
  (unless allowed in config), market closed or outside the entry window, price outside today's
  daily limit, loss at the stop (measured from the HIGHER of the order price and a fresh price)
  above max loss per trade, reward:risk under the minimum, today's total risk above the daily limit,
  too many trades / orders today, position above the cap, cash buffer broken, same order twice.
Warnings (do not block): buy queue (likely no fill), sell queue, real money leaving, Time Machine
verdict negative.
SELL orders (getting out) are never blocked by daily limits; only by a malformed order, a halted
symbol, a closed market or a price outside the band.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "iran-common"))
import iran as I  # noqa: E402


def journal_today():
    j = I.read_json("journal.json", {}) or {}
    return j, j.setdefault("days", {}).setdefault(I.today_key(), {"orders": [], "risk_rial": 0, "entries": 0})


def check(o: dict, cfg: dict) -> dict:
    blocks, warns, passes = [], [], []

    def need(cond, ok_msg, bad_msg):
        (passes if cond else blocks).append(ok_msg if cond else bad_msg)

    side = o.get("side")
    try:
        qty, price = int(o.get("qty") or 0), float(o.get("price") or 0)
    except (TypeError, ValueError):
        qty, price = 0, 0
    need(side in ("buy", "sell") and qty > 0 and price > 0 and o.get("insCode"),
         "سفارش سالم است", "سفارش ناقص است (نماد/سمت/تعداد/قیمت)")
    if blocks:
        return {"verdict": "BLOCK", "blocks": blocks, "warnings": warns, "passes": passes}

    q = I.quote(o["insCode"])
    st = I.market_status(cfg)
    fb, fs = I.fees(cfg)

    paper = I.is_paper(cfg)
    next_session = paper and not st["open"]       # paper: an off-hours order waits for the next session
    need(q["state_code"] == "A", f"وضعیت نماد: {q['state'] or 'مجاز'}", f"نماد قابل معامله نیست: {q['state']}")
    if next_session:
        warns.append(f"بازار بسته است ({st['reason']}); سفارش آزمایشی برای جلسه بعد ({I.jdate(I.next_session(cfg))}) ثبت می‌شود.")
        base = q["close"] or q["last"]
        bp = float(cfg.get("band_pct", 0.03))
        lo, hi = I.round_tick(base * (1 - bp), cfg, down=False), I.round_tick(base * (1 + bp), cfg)
        need(lo <= price <= hi, f"قیمت داخل دامنه تقریبی جلسه بعد ({I.price(lo)}–{I.price(hi)})",
             f"قیمت {I.price(price)} خارج از دامنه تقریبی جلسه بعد ({I.price(lo)}–{I.price(hi)}) است")
    else:
        need(st["open"] or st["state"] == "pre_open" and side == "sell",
             "بازار باز است", f"بازار بسته است: {st['reason']}")
        need(q["band_min"] <= price <= q["band_max"],
             f"قیمت داخل دامنه مجاز ({I.price(q['band_min'])}–{I.price(q['band_max'])})",
             f"قیمت {I.price(price)} خارج از دامنه مجاز امروز ({I.price(q['band_min'])}–{I.price(q['band_max'])}) است")

    if side == "sell":
        if q["queue"] == "sell_queue":
            warns.append("نماد در صف فروش است: فروش ممکن است انجام نشود؛ قیمت را روی کف بگذارید و در صف بمانید.")
        return {"verdict": "BLOCK" if blocks else "PASS", "blocks": blocks, "warnings": warns, "passes": passes,
                "quote": {"last": q["last"], "queue": q["queue"]}}

    # ---- buy only below
    sym = I.norm(o["symbol"])
    need(sym not in {I.norm(s) for s in cfg["blocked_symbols"]}, "نماد مسدود نیست", "نماد در فهرست مسدود شماست")
    if q["yVal"] in I.BASE_YVALS:
        need(cfg["allow_base_market"], "بازار پایه مجاز است", "نماد در بازار پایه است (در config مجاز نیست)")
    if q["under_supervision"]:
        need(cfg["allow_under_supervision"], "", "نماد تحت احتیاط/نظارت است (در config مجاز نیست)")
    if not next_session:
        need(st["in_entry_window"], f"داخل پنجره ورود {cfg['entry_window'][0]}–{cfg['entry_window'][1]}",
             f"خارج از پنجره ورود ({cfg['entry_window'][0]}–{cfg['entry_window'][1]})")
    stop, target = o.get("stop"), o.get("target")
    need(bool(stop) and stop < price, "حد ضرر زیر قیمت دارد", "حد ضرر ندارد یا بالای قیمت است")
    need(bool(target) and target > price, "هدف بالای قیمت دارد", "هدف ندارد یا زیر قیمت است")
    if blocks:
        return {"verdict": "BLOCK", "blocks": blocks, "warnings": warns, "passes": passes}

    ref = max(price, q["last"] or 0)
    risk_ps = ref * (1 + fb) - stop * (1 - fs)
    loss = qty * risk_ps
    if cfg.get("max_loss_per_trade_toman"):
        lim = cfg["max_loss_per_trade_toman"] * 10
        need(loss <= lim * 1.0001, f"ضرر در حد ضرر {I.money(loss, cfg)} ≤ {I.money(lim, cfg)}",
             f"ضرر در حد ضرر {I.money(loss, cfg)} (از قیمت {I.price(ref)}) بیشتر از سقف {I.money(lim, cfg)} است")
    else:
        warns.append("حداکثر ضرر هر معامله تعیین نشده (budget.py rules --max-loss).")
    rr = (target * (1 - fs) - ref * (1 + fb)) / risk_ps
    need(rr >= cfg["min_reward_risk"], f"R:R {rr:.2f} ≥ {cfg['min_reward_risk']}",
         f"R:R {rr:.2f} کمتر از حداقل {cfg['min_reward_risk']} است")

    j, day = journal_today()
    if paper:   # paper orders count toward the same daily limits (placed today)
        pst = I.paper_state() or {"orders": []}
        sess = int((I.now_tehran().date() if st["open"] else I.next_session(cfg)).strftime("%Y%m%d"))
        mine = [x for x in pst["orders"] if x["valid_date"] == sess and x["status"] != "cancelled"]
        day = {"orders": mine, "entries": sum(1 for x in mine if x["side"] == "buy"),
               "risk_rial": sum(x["qty"] * (x["price"] * (1 + fb) - (x.get("stop") or x["price"]) * (1 - fs))
                                for x in mine if x["side"] == "buy"),
               }
        day["orders"] = [{"id": x.get("ref_order")} for x in mine]
    if cfg.get("max_daily_loss_toman"):
        lim = cfg["max_daily_loss_toman"] * 10
        used = day["risk_rial"]
        need(used + loss <= lim, f"ریسک روز: {I.money(used + loss, cfg)} از {I.money(lim, cfg)}",
             f"ریسک امروز با این سفارش {I.money(used + loss, cfg)} می‌شود؛ بیشتر از سقف روزانه {I.money(lim, cfg)}")
    need(day["entries"] < cfg["max_trades_per_day"], f"معامله امروز {day['entries']}/{cfg['max_trades_per_day']}",
         f"به سقف {cfg['max_trades_per_day']} معامله امروز رسیده‌اید")
    need(len(day["orders"]) < cfg["max_orders_per_day"], "تعداد سفارش امروز مجاز است",
         f"به سقف {cfg['max_orders_per_day']} سفارش امروز رسیده‌اید")
    need(o.get("id") not in [x.get("id") for x in day["orders"]], "سفارش تکراری نیست", "همین سفارش امروز قبلاً ارسال شده")

    value = qty * price * (1 + fb)
    equity, free = I.account_equity_rial(cfg), I.account_cash_rial(cfg)
    if equity:
        held = sum(p_["qty"] * (p_.get("last") or p_["avg_price"]) for p_ in I.open_positions(cfg)
                   if p_.get("insCode") == o["insCode"])
        need(value + held <= equity * cfg["max_position_pct"] / 100 * 1.0001,
             f"ارزش {I.money(value + held, cfg)} ≤ {cfg['max_position_pct']}% دارایی",
             f"ارزش این سهم با سفارش {I.money(value + held, cfg)} بیشتر از {cfg['max_position_pct']}% دارایی است")
        need(free - value >= equity * cfg["cash_buffer_pct"] / 100,
             f"ذخیره نقد {cfg['cash_buffer_pct']}% حفظ می‌شود",
             f"نقد آزاد {I.money(free, cfg)} کافی نیست یا ذخیره {cfg['cash_buffer_pct']}% شکسته می‌شود")
    if cfg.get("max_order_toman"):
        need(value <= cfg["max_order_toman"] * 10, "زیر سقف هر سفارش", "بیشتر از سقف هر سفارش")

    if q["queue"] == "buy_queue":
        warns.append("نماد در صف خرید است: سفارش به ته صف می‌رود و ممکن است پر نشود.")
    if q["queue"] == "sell_queue":
        warns.append("نماد در صف فروش است: خرید در صف فروش یعنی گرفتن چاقوی در حال سقوط.")
    try:
        f = I.client_type(o["insCode"])
        if f["real_net_vol"] < 0 and (f.get("real_power") or 1) < 0.7:
            warns.append(f"پول حقیقی امروز در حال خروج است (قدرت خریدار {f['real_power']}).")
    except I.IranError:
        pass
    tm = I.read_json("timemachine.json", {}) or {}
    if tm.get("symbol") == o["symbol"] and tm.get("verdict", "").startswith("منفی"):
        warns.append("حکم ماشین زمان برای این برنامه منفی بود.")
    if o["symbol"] and (I.read_json("signals.json", {}) or {}).get("from_signal") == o["symbol"]:
        warns.append("این ایده از سیگنال تلگرام آمده؛ سیگنال نظر است، نه دلیل.")

    return {"verdict": "BLOCK" if blocks else "PASS", "blocks": blocks, "warnings": warns, "passes": passes,
            "loss_at_stop_rial": round(loss), "rr": round(rr, 2), "ref_price": ref,
            "quote": {"last": q["last"], "queue": q["queue"]}}


def cmd_check(a):
    cfg = I.config()
    ords = I.read_json("orders.json", {}) or {}
    o = ords.get("pending")
    if not o:
        I.die("سفارش پیش‌نویسی در trader/orders.json نیست (اول /iran-budget یا broker.py close).")
    o["id"] = o.get("id") or I.order_hash(o)
    r = check(o, cfg)
    r.update(order_id=o["id"], symbol=o["symbol"], side=o["side"], qty=o["qty"], price=o["price"],
             checked_at=I.market_status(cfg)["now"])
    o["risk"] = {"verdict": r["verdict"], "checked_at": r["checked_at"], "id": o["id"]}
    I.write_json("orders.json", ords)
    log = I.read_json("risk_log.json", {}) or {}
    log.setdefault(I.today_key(), []).append(r)
    I.write_json("risk_log.json", log)

    side = "خرید" if o["side"] == "buy" else "فروش"
    print(f"■ {r['verdict']}  —  {side} {o['qty']:,} {o['symbol']} @ {I.price(o['price'])}  (سفارش {o['id']})")
    for b in r["blocks"]:
        print(f"  ✖ {b}")
    for w in r["warnings"]:
        print(f"  ⚠ {w}")
    for p_ in r["passes"]:
        if p_:
            print(f"  ✓ {p_}")
    if r["verdict"] == "PASS":
        print("\nبعدی: /iran-broker (بلیت سفارش را نشان می‌دهد و بدون «بله»ی شما چیزی ارسال نمی‌کند)")
    else:
        print("\nاین سفارش به کارگزاری نمی‌رود.")


def cmd_today(a):
    cfg = I.config()
    j, day = journal_today()
    lim = cfg.get("max_daily_loss_toman")
    print(f"امروز {I.jdate(I.now_tehran().date())}: {day['entries']} ورود، {len(day['orders'])} سفارش، "
          f"ریسک باز {I.money(day['risk_rial'], cfg)}" + (f" از {I.money(lim*10, cfg)}" if lim else ""))
    for o in day["orders"]:
        print(f"  {o.get('time','')} {o['side']} {o['qty']:,} {o['symbol']} @ {I.price(o['price'])}  ریسک {I.money(o.get('risk_rial', 0), cfg)}")


def cmd_log(a):
    log = I.read_json("risk_log.json", {}) or {}
    for d in sorted(log)[-a.days:]:
        print(d)
        for r in log[d]:
            print(f"  {r['checked_at'][-5:]} {r['verdict']:<5} {r['side']} {r['qty']:,} {r['symbol']} @ {I.price(r['price'])}"
                  + (f"  ← {r['blocks'][0]}" if r["blocks"] else ""))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    sp.add_parser("check")
    sp.add_parser("today")
    l = sp.add_parser("log")
    l.add_argument("--days", type=int, default=3)
    a = p.parse_args()
    {"check": cmd_check, "today": cmd_today, "log": cmd_log}[a.cmd](a)


if __name__ == "__main__":
    I.run(main)
