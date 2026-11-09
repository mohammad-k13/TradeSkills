"""iran-signals: read PUBLIC Telegram channels that post stock signals, pull out symbol / entry /
targets / stop, and grade every channel against what the price really did. Never trades.

  python signals.py add CHANNEL [CHANNEL...]   # username or https://t.me/name (public channels only)
  python signals.py remove CHANNEL
  python signals.py channels
  python signals.py fetch [--pages 3]          # read new posts, store parsed signals
  python signals.py list [--days 3] [--symbol X] [--channel X]
  python signals.py score [--sessions 10] [--channel X]   # each channel's track record
  python signals.py use ID                     # turn a signal into an /iran-exit command (still needs risk checks)

How it reads: https://t.me/s/<channel> (Telegram's public web preview, no login, no bot).
Private channels, and channels that turned the preview off, cannot be read.
A post counts as a signal when it names a share (#فولاد, «فولاد», نماد فولاد, or a known symbol next to
words like خرید / ورود / هدف / حد ضرر). Numbers after ورود/خرید, هدف/تارگت, حد ضرر/استاپ are taken as
entry, targets and stop (Rial; Toman figures are detected and converted).
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "iran-common"))
import iran as I  # noqa: E402

KW = ["خرید", "ورود", "هدف", "تارگت", "حد ضرر", "حدضرر", "استاپ", "سیگنال", "پیشنهاد", "سود", "نقطه"]
NUM = r"(\d[\d,٬.]*)"


def chan_name(s: str) -> str:
    s = s.strip().rstrip("/")
    s = re.sub(r"^(https?://)?(www\.)?(t|telegram)\.me/(s/)?", "", s)
    return s.lstrip("@")


def store():
    return I.read_json("signals.json", {"posts_seen": {}, "signals": [], "next_id": 1}) or \
        {"posts_seen": {}, "signals": [], "next_id": 1}


def fetch_page(ch, before=None):
    url = f"https://t.me/s/{ch}" + (f"?before={before}" if before else "")
    h = I.http_get(url, as_json=False, timeout=25, retries=2)
    posts = []
    for m in re.finditer(r'data-post="([^"/]+)/(\d+)"(.*?)(?=data-post="|$)', h, re.S):
        body = m.group(3)
        tm = re.search(r'<time[^>]+datetime="([^"]+)"', body)
        tx = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', body, re.S)
        if not tx:
            continue
        text = re.sub(r"<br\s*/?>", "\n", tx.group(1))
        text = html.unescape(re.sub(r"<[^>]+>", "", text)).strip()
        t = dt.datetime.fromisoformat(tm.group(1)).astimezone(I.TEHRAN) if tm else None
        posts.append({"channel": ch, "id": int(m.group(2)), "time": t, "text": text,
                      "url": f"https://t.me/{ch}/{m.group(2)}"})
    return posts


def num(s):
    s = I.norm(s).replace(",", "").replace("٬", "")
    try:
        return float(s.rstrip("."))
    except ValueError:
        return None


def parse(post, uni):
    t = I.norm(post["text"])
    syms = []
    for m in re.finditer(r"(?:#|«|نماد\s+)([؀-ۿ]{2,12})", t):
        s = m.group(1).replace("_", "")
        if s in uni:
            syms.append(s)
    has_kw = any(I.norm(k) in t for k in KW)
    if not syms and has_kw:
        for tok in re.findall(r"[؀-ۿ]{3,12}", t):
            if tok in uni and len(tok) >= 4:
                syms.append(tok)
    syms = list(dict.fromkeys(syms))
    if not syms:
        return None
    entry = None
    m = re.search(r"(?:ورود|خرید|محدوده خرید|نقطه ورود|قیمت ورود)\s*(?:در|زیر|:|：|-)?\s*" + NUM +
                  r"(?:\s*(?:تا|-|الی)\s*" + NUM + ")?", t)
    if m:
        a, b = num(m.group(1)), num(m.group(2)) if m.group(2) else None
        entry = (a + b) / 2 if a and b else a
    targets = [num(x) for x in re.findall(r"(?:هدف|تارگت|target|tp)(?:\s*(?:اول|دوم|سوم|چهارم|[1-4](?=\s*[:：-])))?"
                                          r"\s*(?::|：|-)?\s*" + NUM, t, re.I)]
    targets = [x for x in targets if x]
    m = re.search(r"(?:حد ?ضرر|استاپ|stop|sl)\s*(?::|：|-)?\s*" + NUM, t, re.I)
    stop = num(m.group(1)) if m else None
    return {"symbols": syms, "entry": entry, "targets": targets, "stop": stop, "has_numbers": bool(entry or targets or stop)}


def price_on(ins, when: dt.datetime):
    """Reference price at signal time: the live last price for today's posts, else that day's close
    (or the previous session's close for posts made before the open)."""
    bars = I.daily(ins, days=120, adjust=False)
    d = int(when.strftime("%Y%m%d"))
    if when.date() == I.now_tehran().date():
        q = I.quote(ins)
        return q["last"] or q["yesterday"], d
    before_open = when.time() < dt.time(9, 0)
    prior = [b for b in bars if b["date"] < d or (b["date"] == d and not before_open)]
    if not prior:
        return None, d
    return prior[-1]["close"], prior[-1]["date"]


def cmd_add(a, remove=False):
    cfg = I.read_json("config.json", {}) or {}
    chans = cfg.get("signal_channels") or []
    for c in a.channels:
        n = chan_name(c)
        if remove:
            chans = [x for x in chans if x.lower() != n.lower()]
            continue
        try:
            ok = fetch_page(n)
        except I.IranError as e:
            I.die(f"کانال {n} باز نشد: {e}")
        if not ok:
            print(f"⚠ {n}: پستی دیده نشد (خصوصی است یا پیش‌نمایش وب خاموش است). اضافه نشد.")
            continue
        if n not in chans:
            chans.append(n)
        print(f"✓ {n}: {len(ok)} پست اخیر خوانده شد.")
    cfg["signal_channels"] = chans
    I.save_config(cfg)
    print("کانال‌ها: " + ("، ".join(chans) or "(هیچ)"))


def cmd_fetch(a):
    cfg = I.config()
    chans = cfg.get("signal_channels") or []
    if not chans:
        I.die("کانالی اضافه نشده: signals.py add <نام کانال>")
    uni = I.universe()
    st = store()
    new_sig = 0
    for ch in chans:
        last = st["posts_seen"].get(ch, 0)
        posts, before = [], None
        for _ in range(a.pages):
            try:
                page = fetch_page(ch, before)
            except I.IranError as e:
                print(f"⚠ {ch}: {e}")
                break
            if not page:
                break
            posts += page
            before = min(p["id"] for p in page)
            if before <= last:
                break
        posts = [p for p in posts if p["id"] > last]
        posts.sort(key=lambda p: p["id"])
        n_ch = 0
        for p in posts:
            r = parse(p, uni)
            if not r:
                continue
            for s in r["symbols"]:
                u = uni[s]
                try:
                    ref, ref_date = price_on(u["insCode"], p["time"])
                except I.IranError:
                    ref, ref_date = None, None
                e, tg, sl = r["entry"], r["targets"], r["stop"]
                # Toman? (numbers ~10x smaller than the price)
                if ref and any(v for v in [e, sl] + tg):
                    vals = [v for v in [e, sl] + tg if v]
                    if all(0.07 < v * 10 / ref < 1.6 for v in vals) and not all(0.6 < v / ref < 1.6 for v in vals):
                        e, sl, tg = (e * 10 if e else None), (sl * 10 if sl else None), [x * 10 for x in tg]
                sig = {"id": st["next_id"], "channel": ch, "post": p["id"], "url": p["url"],
                       "time": p["time"].isoformat() if p["time"] else None, "symbol": u["symbol"],
                       "insCode": u["insCode"], "entry": e, "targets": tg, "stop": sl, "ref_price": ref,
                       "ref_date": ref_date, "kind": "signal" if r["has_numbers"] else "mention",
                       "text": p["text"][:500]}
                st["next_id"] += 1
                st["signals"].append(sig)
                n_ch += 1
        if posts:
            st["posts_seen"][ch] = max(p["id"] for p in posts)
        print(f"{ch}: {len(posts)} پست تازه، {n_ch} سیگنال/اشاره")
        new_sig += n_ch
    I.write_json("signals.json", st)
    if new_sig:
        a.days, a.symbol, a.channel = 1, None, None
        cmd_list(a, only_new=new_sig)


def fmt_sig(s):
    t = dt.datetime.fromisoformat(s["time"]) if s["time"] else None
    when = (t.strftime("%H:%M ") + I.jdate(t.date())) if t else "—"
    parts = [f"#{s['id']} [{when}] {s['channel']}: {s['symbol']}"]
    if s["kind"] == "signal":
        if s["entry"]:
            parts.append(f"ورود {I.price(s['entry'])}")
        if s["targets"]:
            parts.append("هدف " + "/".join(I.price(x) for x in s["targets"]))
        if s["stop"]:
            parts.append(f"حد ضرر {I.price(s['stop'])}")
    else:
        parts.append("(اشاره بدون عدد)")
    if s.get("ref_price"):
        parts.append(f"قیمت آن لحظه {I.price(s['ref_price'])}")
    return "  ".join(parts) + f"\n      {s['url']}"


def cmd_list(a, only_new=None):
    st = store()
    rows = st["signals"][-only_new:] if only_new else st["signals"]
    since = I.now_tehran() - dt.timedelta(days=a.days)
    for s in reversed(rows):
        if s["time"] and dt.datetime.fromisoformat(s["time"]) < since:
            continue
        if a.symbol and I.norm(s["symbol"]) != I.norm(a.symbol):
            continue
        if a.channel and s["channel"].lower() != chan_name(a.channel).lower():
            continue
        print(fmt_sig(s))
    print("\nسیگنال نظر یک کانال است، نه دلیل خرید. قبل از هر کاری: /iran-news (کدال)، /iran-timemachine، /iran-risk.")


def grade(s, sessions):
    ref = s.get("entry") or s.get("ref_price")
    if not ref or not s.get("ref_date"):
        return None
    bars = [b for b in I.daily(s["insCode"], days=200, adjust=False) if b["date"] > s["ref_date"]][:sessions]
    if not bars:
        return None
    tgt = s["targets"][0] if s.get("targets") else None
    stop = s.get("stop")
    out = "open"
    for b in bars:
        if stop and b["low"] <= stop:
            out = "stop"
            break
        if tgt and b["high"] >= tgt:
            out = "target"
            break
    if out == "open" and len(bars) >= sessions:
        out = "time"
    r5 = (bars[min(4, len(bars) - 1)]["close"] / ref - 1) * 100
    rN = (bars[-1]["close"] / ref - 1) * 100
    pre = [b for b in I.daily(s["insCode"], days=200, adjust=False) if b["date"] <= s["ref_date"]][-6:]
    run_up = (pre[-1]["close"] / pre[0]["close"] - 1) * 100 if len(pre) >= 2 else None
    return {"outcome": out, "ret5": r5, "retN": rN, "sessions": len(bars), "run_up_before": run_up,
            "max_up": (max(b["high"] for b in bars) / ref - 1) * 100,
            "max_down": (min(b["low"] for b in bars) / ref - 1) * 100}


def cmd_score(a):
    st = store()
    by = {}
    for s in st["signals"]:
        if a.channel and s["channel"].lower() != chan_name(a.channel).lower():
            continue
        try:
            g = grade(s, a.sessions)
        except I.IranError:
            g = None
        if g:
            by.setdefault(s["channel"], []).append((s, g))
    if not by:
        I.die("هنوز سیگنالی که حداقل یک جلسه از آن گذشته باشد نیست. چند روز fetch بزنید، بعد score.")
    print(f"کارنامه کانال‌ها (حداکثر {a.sessions} جلسه بعد از هر سیگنال، بدون کارمزد):\n")
    for ch, rows in sorted(by.items(), key=lambda kv: -len(kv[1])):
        n = len(rows)
        sig = [g for s, g in rows if s["kind"] == "signal" and (s.get("targets") or s.get("stop"))]
        tg = sum(1 for g in sig if g["outcome"] == "target")
        sp = sum(1 for g in sig if g["outcome"] == "stop")
        avg5 = sum(g["ret5"] for _, g in rows) / n
        avgN = sum(g["retN"] for _, g in rows) / n
        win = sum(1 for _, g in rows if g["retN"] > 1.25) / n * 100
        pumped = sum(1 for _, g in rows if (g["run_up_before"] or 0) > 10)
        print(f"■ {ch}: {n} سیگنال/اشاره  |  میانگین بازده ۵ جلسه {avg5:+.2f}%  |  {a.sessions} جلسه {avgN:+.2f}%"
              f"  |  بیش از کارمزد سود داد: {win:.0f}%")
        if sig:
            print(f"    با هدف/حد ضرر: {len(sig)}  ← اول هدف {tg} ({tg/len(sig)*100:.0f}%)، اول حد ضرر {sp} ({sp/len(sig)*100:.0f}%)")
        if pumped:
            print(f"    ⚠ {pumped} سیگنال بعد از رشد بیش از ۱۰٪ در ۵ روز قبل داده شده (احتمال پامپ برای تخلیه).")
        if n < 20:
            print("    (نمونه کم است؛ تا ۲۰+ سیگنال قضاوت نکنید.)")
    print("\nبازده‌ها از قیمت ورود اعلامی (یا قیمت لحظه سیگنال) با قیمت‌های واقعی TSETMC حساب شده‌اند.")


def cmd_use(a):
    st = store()
    s = next((x for x in st["signals"] if x["id"] == a.id), None)
    if not s:
        I.die(f"سیگنال #{a.id} نیست.")
    print(fmt_sig(s))
    cmd = f"python exit.py plan {s['symbol']}"
    if s.get("entry"):
        cmd += f" --entry {s['entry']:.0f}"
    if s.get("stop"):
        cmd += f" --stop price:{s['stop']:.0f}"
    if s.get("targets"):
        cmd += f" --target price:{s['targets'][0]:.0f}"
    st["from_signal"] = s["symbol"]
    I.write_json("signals.json", st)
    print(f"\nبرای برنامه‌ی خروج (در پوشه iran-exit):\n  {cmd}\n"
          "سپس /iran-timemachine و /iran-risk. ریسک‌منیجر یادداشت می‌کند که ایده از سیگنال آمده است.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    ad = sp.add_parser("add")
    ad.add_argument("channels", nargs="+")
    rm = sp.add_parser("remove")
    rm.add_argument("channels", nargs="+")
    sp.add_parser("channels")
    f = sp.add_parser("fetch")
    f.add_argument("--pages", type=int, default=3)
    l = sp.add_parser("list")
    l.add_argument("--days", type=float, default=3)
    l.add_argument("--symbol")
    l.add_argument("--channel")
    sc = sp.add_parser("score")
    sc.add_argument("--sessions", type=int, default=10)
    sc.add_argument("--channel")
    u = sp.add_parser("use")
    u.add_argument("id", type=int)
    a = p.parse_args()
    if a.cmd == "channels":
        print("کانال‌ها: " + ("، ".join(I.config().get("signal_channels") or []) or "(هیچ)"))
        return
    {"add": cmd_add, "remove": lambda a: cmd_add(a, remove=True), "fetch": cmd_fetch, "list": cmd_list,
     "score": cmd_score, "use": cmd_use}[a.cmd](a)


if __name__ == "__main__":
    I.run(main)
