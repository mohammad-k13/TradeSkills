"""iran-exit: set the stop and the target BEFORE you buy. Long only. Writes trader/plan.json.

  python exit.py plan [SYMBOL] [--entry PRICE] [--stop MODE] [--target MODE] [--hold 10]
  python exit.py show

--entry   default: the triggered entry in trader/entry.json, else the live last price
--stop    atr:1.5 (default: 1.5 x the 14-day ATR) | or-mid | or-low  (opening range from iran-entry)
          | pct:4 (4% under entry) | low:5 (lowest low of the last 5 sessions) | price:4410
--target  r:2 (default: 2R AFTER fees) | price:5200 | pct:8
--hold    max sessions to hold before the plan says "exit at the close" (swing; default 10)

Iran rules it applies
  * R is measured after fees: risk/share = entry*(1+fee_buy) - stop*(1-fee_sell).
  * Refuses a stop at/above the entry, a target at/below it, and a stop so tight that the
    round-trip fees (~1.25%) eat more than half of the risk.
  * The daily limit (دامنه نوسان, usually ±3%) caps each day's move: it says how many sessions
    the target needs at the very least, and warns when the stop is below today's lower limit
    (it can only be hit on a later day) and that in a sell queue (صف فروش) a stop may not fill.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "iran-common"))
import iran as I  # noqa: E402


def parse_mode(s: str, default_val: float):
    if ":" in s:
        k, v = s.split(":", 1)
        return k, float(v)
    return s, default_val


def build(a, cfg) -> dict:
    ent = I.read_json("entry.json", {}) or {}
    sym = a.symbol or ent.get("last")
    if not sym:
        I.die("نماد بدهید: exit.py plan فولاد --entry 4600")
    info = I.resolve(sym)
    e_row = (ent.get("symbols") or {}).get(info["symbol"], {})
    q = I.quote(info["insCode"])
    fb, fs = I.fees(cfg)
    warnings = []

    if a.entry:
        entry, src = a.entry, "--entry"
    elif e_row.get("state") == "triggered":
        entry, src = e_row["entry"], f"iran-entry ({e_row.get('trigger_time')})"
    else:
        entry, src = q["last"], "live last price"
        warnings.append("ورود هنوز فعال نشده؛ قیمت آخرین معامله به‌عنوان ورود فرض شد.")

    bars = I.daily(info["insCode"], days=60)
    mode, val = parse_mode(a.stop, 1.5)
    if mode == "atr":
        at = I.atr(bars, 14)
        if not at:
            I.die("تاریخچه کافی برای ATR نیست؛ --stop pct:4 یا price:... بدهید.")
        stop, why = entry - val * at, f"{val} × ATR14 ({I.price(at)})"
    elif mode in ("or-mid", "or-low"):
        if "or_high" not in e_row:
            I.die("دامنه آغازین در entry.json نیست؛ اول /iran-entry را اجرا کنید یا حالت دیگری بدهید.")
        stop = e_row["or_mid"] if mode == "or-mid" else e_row["or_low"]
        why = "میانه دامنه آغازین" if mode == "or-mid" else "کف دامنه آغازین"
    elif mode == "pct":
        stop, why = entry * (1 - val / 100), f"{val}% زیر ورود"
    elif mode == "low":
        n = int(val or 5)
        stop, why = min(b["low"] for b in bars[-n:]) - float(cfg["tick_rial"]), f"کف {n} روز اخیر"
    elif mode == "price":
        stop, why = val, "قیمت شما"
    else:
        I.die(f"حالت حد ضرر ناشناخته: {a.stop}")
    stop = I.round_tick(stop, cfg, down=True)

    if stop >= entry:
        I.die(f"حد ضرر ({I.price(stop)}) باید زیر قیمت ورود ({I.price(entry)}) باشد.")
    cost_in = entry * (1 + fb)
    risk = cost_in - stop * (1 - fs)
    fee_part = entry * fb + stop * fs
    if fee_part > 0.5 * risk:
        I.die(f"حد ضرر خیلی نزدیک است: از ریسک {I.price(risk)} ریال/سهم، {I.price(fee_part)} فقط کارمزد است. "
              f"حد ضرر را پایین‌تر بگذارید (مثلاً --stop atr:1.5 یا pct:4).")

    tmode, tval = parse_mode(a.target, 2.0)
    if tmode == "r":
        target = (cost_in + tval * risk) / (1 - fs)
        twhy = f"{tval}R پس از کارمزد"
    elif tmode == "pct":
        target, twhy = entry * (1 + tval / 100), f"{tval}% بالای ورود"
    elif tmode == "price":
        target, twhy = tval, "قیمت شما"
    else:
        I.die(f"حالت هدف ناشناخته: {a.target}")
    target = I.round_tick(target, cfg, down=False)
    if target <= entry:
        I.die(f"هدف ({I.price(target)}) باید بالای ورود باشد.")
    reward = target * (1 - fs) - cost_in
    rr = reward / risk

    bp = I.band_pct(q) or cfg["band_pct"]
    min_days = max(1, math.ceil(math.log(target / entry) / math.log(1 + bp)))
    if q["band_min"] and stop < q["band_min"]:
        warnings.append(f"حد ضرر زیر کف مجاز امروز ({I.price(q['band_min'])}) است: امروز فعال نمی‌شود، "
                        f"در روزهای بعد ممکن است با گپ پایین‌تر بفروشید.")
    if q["band_max"] and target > q["band_max"]:
        warnings.append(f"هدف بالاتر از سقف امروز ({I.price(q['band_max'])}) است: حداقل {min_days} جلسه لازم دارد.")
    if q["queue"] == "sell_queue":
        warnings.append("نماد همین حالا در صف فروش است: خرید نکنید مگر دلیل قوی دارید.")
    if min_days > a.hold:
        warnings.append(f"هدف حداقل {min_days} جلسه لازم دارد ولی نگهداری {a.hold} جلسه است.")
    warnings.append("حد ضرر در بورس ایران تضمینی نیست: در صف فروش ممکن است فروش انجام نشود. "
                    "یا سفارش شرطی کارگزاری (اگر دارد) بگذارید یا با /iran-alerts هشدار بگیرید و خودتان بفروشید.")
    if src == "live last price" and q["queue"] == "buy_queue":
        warnings.append("نماد در صف خرید است؛ خرید به این قیمت احتمالاً پر نمی‌شود.")

    return {"symbol": info["symbol"], "insCode": info["insCode"], "name": info.get("name"), "side": "buy",
            "entry": entry, "entry_source": src, "stop": stop, "stop_rule": why, "target": target,
            "target_rule": twhy, "risk_per_share_rial": round(risk, 2), "reward_per_share_rial": round(reward, 2),
            "rr_after_fees": round(rr, 2), "fees": {"buy": fb, "sell": fs}, "hold_sessions": a.hold,
            "min_sessions_to_target": min_days, "band_pct": bp, "band_today": [q["band_min"], q["band_max"]],
            "queue_now": q["queue"], "warnings": warnings, "created_at": I.market_status(cfg)["now"]}


def show(p):
    print(f"■ برنامه خروج {p['symbol']}  ({p.get('created_at')})")
    print(f"  ورود  {I.price(p['entry']):>10}   ← {p['entry_source']}")
    print(f"  حد ضرر {I.price(p['stop']):>9}   ← {p['stop_rule']}  ({(p['stop']/p['entry']-1)*100:+.2f}%)")
    print(f"  هدف   {I.price(p['target']):>10}   ← {p['target_rule']}  ({(p['target']/p['entry']-1)*100:+.2f}%)")
    print(f"  ریسک هر سهم (با کارمزد): {I.price(p['risk_per_share_rial'])} ریال   سود هر سهم: "
          f"{I.price(p['reward_per_share_rial'])} ریال   R:R = {p['rr_after_fees']}")
    print(f"  نگهداری حداکثر {p['hold_sessions']} جلسه؛ رسیدن به هدف حداقل {p['min_sessions_to_target']} جلسه")
    for w in p["warnings"]:
        print(f"  ⚠ {w}")
    print(f"\nذخیره شد: {I.path('plan.json')}   بعدی: /iran-timemachine (شانس‌ها) سپس /iran-budget (تعداد سهم)")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    c = sp.add_parser("plan")
    c.add_argument("symbol", nargs="?")
    c.add_argument("--entry", type=float)
    c.add_argument("--stop", default="atr:1.5")
    c.add_argument("--target", default="r:2")
    c.add_argument("--hold", type=int, default=10)
    sp.add_parser("show")
    a = p.parse_args()
    cfg = I.config()
    if a.cmd == "plan":
        plan = build(a, cfg)
        I.write_json("plan.json", plan)
        show(plan)
    else:
        plan = I.read_json("plan.json")
        if not plan:
            I.die("هنوز برنامه‌ای نیست.")
        show(plan)


if __name__ == "__main__":
    I.run(main)
