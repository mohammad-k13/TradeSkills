"""iran-alerts: rings when a price, a stop, a queue or the opening bell hits. Each alert rings once.

  python alerts.py add SYMBOL above|below|stop|target PRICE [--note ...]
  python alerts.py add SYMBOL pct +3 | pct -2          # move from yesterday's close
  python alerts.py add SYMBOL buy_queue_break          # صف خرید شکست (queue at the upper limit broke)
  python alerts.py add SYMBOL sell_queue               # صف فروش تشکیل شد
  python alerts.py add SYMBOL buy_queue                # صف خرید تشکیل شد
  python alerts.py add - time 12:20 [--note "flat?"]  # any Tehran time (symbol '-')
  python alerts.py add - open                          # opening bell (next session)
  python alerts.py from-plan                           # stop + target from trader/plan.json
  python alerts.py from-positions                      # stop + target for every open position
  python alerts.py list | remove ID | clear
  python alerts.py check                               # one pass: prints what rang
  python alerts.py watch [--every 60] [--until 12:30]  # loop until the time; prints rings as they happen
  python alerts.py price SYMBOL [SYMBOL...]            # quick quotes
  python alerts.py market                              # is the market open?
Writes trader/prices.json (last quotes) for the other skills.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "iran-common"))
import iran as I  # noqa: E402

KINDS = {"above", "below", "stop", "target", "pct", "buy_queue_break", "buy_queue", "sell_queue", "time", "open"}


def load():
    return I.read_json("alerts.json", {"next_id": 1, "alerts": []}) or {"next_id": 1, "alerts": []}


def add(store, **a):
    a["id"] = store["next_id"]
    store["next_id"] += 1
    a.update(created=I.market_status()["now"], rung=None)
    store["alerts"].append(a)
    return a


def describe(a):
    k = a["kind"]
    s = a.get("symbol") or ""
    if k in ("above", "below", "stop", "target"):
        lab = {"above": "بالای", "below": "زیر", "stop": "حد ضرر", "target": "هدف"}[k]
        return f"{s} {lab} {I.price(a['price'])}"
    if k == "pct":
        return f"{s} تغییر {a['pct']:+}% از دیروز"
    if k == "time":
        return f"ساعت {a['at']}"
    if k == "open":
        return "زنگ بازگشایی بازار"
    return f"{s} " + {"buy_queue_break": "شکست صف خرید", "buy_queue": "تشکیل صف خرید", "sell_queue": "تشکیل صف فروش"}[k]


def cmd_add(a):
    st = load()
    k = a.kind
    if k not in KINDS:
        I.die(f"نوع هشدار ناشناخته: {k}. یکی از: {', '.join(sorted(KINDS))}")
    rec = {"kind": k, "note": a.note}
    if a.symbol != "-":
        info = I.resolve(a.symbol)
        rec.update(symbol=info["symbol"], insCode=info["insCode"])
    if k in ("above", "below", "stop", "target"):
        rec["price"] = float(a.value)
    elif k == "pct":
        rec["pct"] = float(a.value)
    elif k == "time":
        rec["at"] = a.value
        rec["date"] = I.today_key()
    elif k == "open":
        rec["date"] = I.next_session().isoformat()
    if k == "buy_queue_break":
        rec["armed"] = False   # arms once the queue is seen, rings when it breaks
    x = add(st, **rec)
    I.write_json("alerts.json", st)
    print(f"#{x['id']} اضافه شد: {describe(x)}")


def cmd_from(a, source):
    st = load()
    rows = []
    if source == "plan":
        p = I.read_json("plan.json")
        if not p:
            I.die("plan.json نیست.")
        rows = [p]
    else:
        rows = (I.read_json("positions.json", {}) or {}).get("open", [])
    for p in rows:
        for k in ("stop", "target"):
            if p.get(k) and not any(x["kind"] == k and x.get("symbol") == p["symbol"] and not x["rung"] for x in st["alerts"]):
                x = add(st, kind=k, symbol=p["symbol"], insCode=p["insCode"], price=p[k], note=None)
                print(f"#{x['id']} {describe(x)}")
    I.write_json("alerts.json", st)


def ring(a, q=None):
    a["rung"] = I.market_status()["now"]
    msg = f"🔔 #{a['id']} {describe(a)}"
    if q:
        msg += f"  —  آخرین {I.price(q['last'])} ({q['chg_pct']:+}%)" + ("  [صف خرید]" if q["queue"] == "buy_queue" else "  [صف فروش]" if q["queue"] == "sell_queue" else "")
    if a["kind"] == "stop":
        msg += "  ← این هشدار است، نه سفارش. برای خروج: broker.py close " + a["symbol"]
    if a.get("note"):
        msg += f"  ({a['note']})"
    print(msg, flush=True)


def check_once(store, cfg) -> int:
    st = I.market_status(cfg)
    now = I.now_tehran()
    live = [x for x in store["alerts"] if not x["rung"]]
    quotes = {}
    for ins in {x["insCode"] for x in live if x.get("insCode")}:
        try:
            quotes[ins] = I.quote(ins)
        except I.IranError as e:
            print(f"⚠ {e}")
    n = 0
    for x in live:
        k = x["kind"]
        if k == "time":
            h, m = map(int, x["at"].split(":"))
            if now.strftime("%Y-%m-%d") >= x["date"] and now.time() >= dt.time(h, m):
                ring(x); n += 1
            continue
        if k == "open":
            if now.date().isoformat() >= x["date"] and st["open"]:
                ring(x); n += 1
            continue
        q = quotes.get(x.get("insCode"))
        if not q or not q["last"] or str(q["date"]) != now.strftime("%Y%m%d"):
            continue   # no trade today yet (or holiday): nothing can ring
        p = q["last"]
        hit = ((k in ("above", "target") and p >= x["price"]) or (k in ("below", "stop") and p <= x["price"])
               or (k == "pct" and q["chg_pct"] is not None and ((x["pct"] >= 0 and q["chg_pct"] >= x["pct"]) or (x["pct"] < 0 and q["chg_pct"] <= x["pct"])))
               or (k == "buy_queue" and q["queue"] == "buy_queue") or (k == "sell_queue" and q["queue"] == "sell_queue"))
        if k == "buy_queue_break":
            if q["queue"] == "buy_queue":
                x["armed"] = True
            elif x.get("armed"):
                hit = True
        if hit:
            ring(x, q); n += 1
    prices = I.read_json("prices.json", {}) or {}
    for ins, q in quotes.items():
        prices[q["symbol"]] = {k: q[k] for k in ("insCode", "last", "close", "yesterday", "band_min", "band_max", "queue", "chg_pct")} | {"at": st["now"]}
    if quotes:
        I.write_json("prices.json", prices)
    I.write_json("alerts.json", store)
    return n


def cmd_check(a):
    store = load()
    if not any(not x["rung"] for x in store["alerts"]):
        print("هشدار فعالی نیست.")
        return
    n = check_once(store, I.config())
    if not n:
        print(f"چیزی زنگ نزد ({I.market_status()['jalali']}).")


def cmd_watch(a):
    cfg = I.config()
    until = a.until or cfg["session_close"]
    h, m = map(int, until.split(":"))
    print(f"مراقبت تا {until} هر {a.every} ثانیه…", flush=True)
    while True:
        store = load()
        if not any(not x["rung"] for x in store["alerts"]):
            print("همه هشدارها زنگ زدند.")
            return
        check_once(store, cfg)
        if I.now_tehran().time() >= dt.time(h, m):
            print(f"ساعت {until} شد؛ مراقبت تمام شد.")
            return
        time.sleep(a.every)


def cmd_list(a):
    for x in load()["alerts"]:
        print(f"#{x['id']:<3} {'✓ ' + x['rung'] if x['rung'] else 'فعال':<20} {describe(x)}" + (f"  ({x['note']})" if x.get("note") else ""))


def cmd_remove(a):
    st = load()
    st["alerts"] = [x for x in st["alerts"] if x["id"] != a.id]
    I.write_json("alerts.json", st)
    print(f"#{a.id} حذف شد.")


def cmd_price(a):
    for s in a.symbols:
        q = I.quote(I.resolve(s)["insCode"])
        print(f"{q['symbol']:<8} آخرین {I.price(q['last'])} ({q['chg_pct']:+}%)  پایانی {I.price(q['close'])}  "
              f"دامنه {I.price(q['band_min'])}–{I.price(q['band_max'])}  {q['state']}"
              + ("  [صف خرید]" if q["queue"] == "buy_queue" else "  [صف فروش]" if q["queue"] == "sell_queue" else "")
              + f"  ({I.jdate(q['date'])} {str(q['time']).zfill(6)[:2]}:{str(q['time']).zfill(6)[2:4]})")


def cmd_market(a):
    st = I.market_status()
    print(f"{st['jalali']} تهران — {st['reason']}. جلسه {st['open_time']}–{st['close_time']}، "
          f"جلسه بعد: {I.jdate(I.next_session())}")
    print("تعطیلات مذهبی (قمری) هر سال جابه‌جا می‌شوند؛ آن‌ها را در config.json → holidays_jalali اضافه کنید.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    ad = sp.add_parser("add")
    ad.add_argument("symbol")
    ad.add_argument("kind")
    ad.add_argument("value", nargs="?")
    ad.add_argument("--note")
    sp.add_parser("from-plan")
    sp.add_parser("from-positions")
    sp.add_parser("list")
    r = sp.add_parser("remove")
    r.add_argument("id", type=int)
    sp.add_parser("clear")
    sp.add_parser("check")
    w = sp.add_parser("watch")
    w.add_argument("--every", type=int, default=60)
    w.add_argument("--until")
    pr = sp.add_parser("price")
    pr.add_argument("symbols", nargs="+")
    sp.add_parser("market")
    a = p.parse_args()
    if a.cmd == "clear":
        I.write_json("alerts.json", {"next_id": 1, "alerts": []})
        print("همه هشدارها پاک شد.")
        return
    {"add": cmd_add, "from-plan": lambda a: cmd_from(a, "plan"), "from-positions": lambda a: cmd_from(a, "pos"),
     "list": cmd_list, "remove": cmd_remove, "check": cmd_check, "watch": cmd_watch, "price": cmd_price,
     "market": cmd_market}[a.cmd](a)


if __name__ == "__main__":
    I.run(main)
