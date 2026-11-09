"""iran-budget: size the position to your cash and your max loss, write ONE order to trader/orders.json.

  python budget.py rules [--cash 50000000] [--max-loss 1000000] [--daily-loss 3000000]
                         [--position-pct 25] [--max-order 20000000] [--buffer 10] [--min-rr 1.5]
                         [--fee-buy 0.003712] [--fee-sell 0.0088]          (amounts in TOMAN)
  python budget.py size [--cash TOMAN] [--max-loss TOMAN] [--price RIAL]
  python budget.py show

Shares = the smallest of four limits (it says which one decided):
  1. max loss:   max_loss / (risk per share after fees)
  2. position:   max_position_pct of cash / cost per share (incl. buy fee)
  3. max order:  max_order / cost per share
  4. cash:       cash * (1 - buffer) / cost per share
A stop too far away for your max loss is a refusal (0 shares), not a smaller order.
Nothing is placed: the order goes to /iran-risk, then /iran-broker.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "iran-common"))
import iran as I  # noqa: E402

RULE_KEYS = {"cash": "cash_toman", "max_loss": "max_loss_per_trade_toman", "daily_loss": "max_daily_loss_toman",
             "position_pct": "max_position_pct", "max_order": "max_order_toman", "buffer": "cash_buffer_pct",
             "min_rr": "min_reward_risk", "fee_buy": "fee_buy", "fee_sell": "fee_sell"}


def cmd_rules(a):
    cfg = I.read_json("config.json", {}) or {}
    changed = False
    for arg, k in RULE_KEYS.items():
        v = getattr(a, arg)
        if v is not None:
            cfg[k] = v
            changed = True
    if changed:
        I.save_config(cfg)
    c = I.config()
    t = lambda k: I.money(c[k] * 10, c) if c.get(k) is not None else "تعیین نشده"  # noqa: E731
    print("قوانین شما:")
    print(f"  نقدینگی              {t('cash_toman')}")
    print(f"  حداکثر ضرر هر معامله  {t('max_loss_per_trade_toman')}")
    print(f"  حداکثر ریسک روزانه    {t('max_daily_loss_toman')}")
    print(f"  سقف هر سهم            {c['max_position_pct']}% نقدینگی")
    print(f"  سقف هر سفارش          {t('max_order_toman')}")
    print(f"  ذخیره نقد             {c['cash_buffer_pct']}%")
    print(f"  حداقل R:R             {c['min_reward_risk']}")
    print(f"  کارمزد خرید/فروش      {c['fee_buy']*100:.4f}% / {c['fee_sell']*100:.4f}%")
    print(f"  تعداد معامله در روز    {c['max_trades_per_day']}")
    print(f"\n{I.path('config.json')}")


def cmd_size(a):
    cfg = I.config()
    plan = I.read_json("plan.json")
    if not plan:
        I.die("trader/plan.json نیست. اول /iran-exit.")
    cash_t = a.cash if a.cash is not None else cfg.get("cash_toman")
    loss_t = a.max_loss if a.max_loss is not None else cfg.get("max_loss_per_trade_toman")
    if not cash_t or not loss_t:
        I.die("نقدینگی و حداکثر ضرر هر معامله را بدهید: budget.py rules --cash 50000000 --max-loss 1000000 (تومان)")
    cash, max_loss = cash_t * 10, loss_t * 10       # -> Rial
    fb, fs = I.fees(cfg)
    q = I.quote(plan["insCode"])
    price = a.price or plan["entry"]
    notes = []
    if q["band_max"] and price > q["band_max"]:
        notes.append(f"قیمت {I.price(price)} بالای سقف امروز بود؛ سفارش روی سقف ({I.price(q['band_max'])}) گذاشته شد.")
        price = q["band_max"]
    if q["band_min"] and price < q["band_min"]:
        I.die(f"قیمت {I.price(price)} زیر کف مجاز امروز ({I.price(q['band_min'])}) است.")
    stop, target = plan["stop"], plan["target"]
    if stop >= price:
        I.die(f"قیمت سفارش ({I.price(price)}) باید بالای حد ضرر ({I.price(stop)}) باشد.")
    cost = price * (1 + fb)
    risk = cost - stop * (1 - fs)
    limits = {
        "max_loss": math.floor(max_loss / risk),
        "position": math.floor(cash * cfg["max_position_pct"] / 100 / cost),
        "cash": math.floor(cash * (1 - cfg["cash_buffer_pct"] / 100) / cost),
    }
    if cfg.get("max_order_toman"):
        limits["max_order"] = math.floor(cfg["max_order_toman"] * 10 / cost)
    qty = min(limits.values())
    decided = min(limits, key=limits.get)
    names = {"max_loss": "حداکثر ضرر هر معامله", "position": "سقف هر سهم", "cash": "نقدینگی (با ذخیره)",
             "max_order": "سقف هر سفارش"}
    if limits["max_loss"] < 1:
        I.die(f"حتی ۱ سهم هم در حداکثر ضرر شما ({I.money(max_loss, cfg)}) جا نمی‌شود: ریسک هر سهم "
              f"{I.price(risk)} ریال است. حد ضرر را نزدیک‌تر کنید یا وارد نشوید.")
    if qty < 1:
        I.die("با این قوانین حتی ۱ سهم هم نمی‌شود خرید.")
    order = {"symbol": plan["symbol"], "insCode": plan["insCode"], "side": "buy", "qty": qty, "price": price,
             "type": "limit", "validity": "day", "stop": stop, "target": target,
             "est_cost_rial": round(qty * cost), "max_loss_rial": round(qty * risk),
             "est_reward_rial": round(qty * (target * (1 - fs) - cost)), "rr_after_fees": plan.get("rr_after_fees"),
             "decided_by": decided, "limits": limits, "notes": notes, "created_at": I.market_status(cfg)["now"],
             "status": "draft"}
    order["id"] = I.order_hash(order)
    I.write_json("orders.json", {"pending": order})
    show(order, cfg)


def show(o, cfg):
    names = {"max_loss": "حداکثر ضرر هر معامله", "position": "سقف هر سهم", "cash": "نقدینگی (با ذخیره)",
             "max_order": "سقف هر سفارش"}
    print(f"■ سفارش پیش‌نویس {o['id']}: خرید {o['qty']:,} سهم {o['symbol']} به قیمت {I.price(o['price'])} ریال (محدود، روز)")
    print(f"  هزینه تقریبی با کارمزد: {I.money(o['est_cost_rial'], cfg)}")
    print(f"  ضرر در حد ضرر {I.price(o['stop'])}: {I.money(o['max_loss_rial'], cfg)}"
          f"   سود در هدف {I.price(o['target'])}: {I.money(o['est_reward_rial'], cfg)}")
    print(f"  تعیین‌کننده: {names[o['decided_by']]}   (" +
          "، ".join(f"{names[k]}={v:,}" for k, v in o["limits"].items()) + ")")
    for n in o.get("notes", []):
        print(f"  ⚠ {n}")
    print(f"\nذخیره شد: {I.path('orders.json')}   هیچ سفارشی ارسال نشد. بعدی: /iran-risk")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("rules")
    for arg in RULE_KEYS:
        r.add_argument("--" + arg.replace("_", "-"), dest=arg, type=float)
    s = sp.add_parser("size")
    s.add_argument("--cash", type=float)
    s.add_argument("--max-loss", type=float)
    s.add_argument("--price", type=float, help="limit price in RIAL (default: plan entry)")
    sp.add_parser("show")
    a = p.parse_args()
    if a.cmd == "rules":
        cmd_rules(a)
    elif a.cmd == "size":
        cmd_size(a)
    else:
        o = (I.read_json("orders.json", {}) or {}).get("pending")
        if not o:
            I.die("سفارش پیش‌نویسی نیست.")
        show(o, I.config())


if __name__ == "__main__":
    I.run(main)
