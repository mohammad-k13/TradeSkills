"""iran-news: what is new for the stocks you watch, newest first, never repeated.

  python news.py check [SYMBOL ...] [--top 15] [--market] [--hours 48] [--all-seen]
  python news.py codal SYMBOL [--pages 1]          # latest Codal letters for one symbol
  python news.py sources                           # list the configured news sites
  python news.py reset                             # forget what was already shown

Sources
  Codal (کدال)          official company announcements: financials, AGM, capital raise, monthly activity
  TSETMC messages       پیام ناظر: halts, reopenings, warnings, trade cancellations
  News sites (config)   سنا، بورس‌نیوز، نبض بورس، شهر بورس، اقتصادنیوز، بورس۲۴ (RSS or HTML)

Which symbols: the ones you name, else your manual watchlist + held positions + the top --top
symbols from the last scan. --market also prints the general market headlines (no symbol match).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import re
import sys
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "iran-common"))
import iran as I  # noqa: E402

TAGS = [  # (tag, Persian label, keywords) - first match wins for the label, all matches are kept
    ("halt", "توقف/بازگشایی", ["توقف", "بازگشایی", "تعلیق", "عدم تایید", "ابطال معاملات"]),
    ("watchdog", "ناظر/احتیاط", ["ناظر", "احتیاط", "تابلوی زرد", "تذکر", "نوسانات غیرعادی", "افشای اطلاعات بااهمیت"]),
    ("capital_raise", "افزایش سرمایه", ["افزایش سرمایه", "حق تقدم", "سهام جایزه", "تجدید ارزیابی"]),
    ("agm", "مجمع", ["مجمع", "آگهی دعوت", "تصمیمات مجمع", "صورتجلسه"]),
    ("dividend", "سود نقدی", ["تقسیم سود", "سود نقدی", "DPS", "زمان‌بندی پرداخت سود"]),
    ("earnings", "صورت مالی", ["صورت‌های مالی", "صورتهای مالی", "اطلاعات و صورت", "EPS", "پیش‌بینی درآمد", "تعدیل"]),
    ("monthly", "گزارش ماهانه", ["گزارش فعالیت ماهانه", "فعالیت ماهانه"]),
    ("deal", "قرارداد/خرید و فروش", ["قرارداد", "واگذاری", "خرید سهام", "فروش سهام", "تملک", "ادغام"]),
    ("legal", "حقوقی/قضایی", ["شکایت", "دادگاه", "حکم", "قضایی", "جریمه"]),
    ("macro", "کلان", ["دلار", "نرخ ارز", "تورم", "نرخ بهره", "بانک مرکزی", "تحریم", "مذاکره", "بودجه", "نفت", "طلا"]),
    ("analysis", "تحلیل/پیش‌بینی", ["تحلیل", "پیش‌بینی", "سیگنال", "پیشنهاد خرید", "چشم‌انداز"]),
]


def tags_for(text: str):
    t = I.norm(text)
    out = [tag for tag, _, kws in TAGS if any(I.norm(k) in t for k in kws)]
    return out or ["general"]


LABEL = {t: l for t, l, _ in TAGS} | {"general": "عمومی"}


def strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def parse_time(s: str):
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
        return d.astimezone(I.TEHRAN) if d.tzinfo else d.replace(tzinfo=I.TEHRAN)
    except Exception:
        pass
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(I.TEHRAN)
    except Exception:
        return I.parse_jdatetime(s)


def fetch_rss(src):
    text = I.http_get(src["url"], as_json=False, timeout=25, retries=2)
    text = re.sub(r"^[^<]+", "", text)
    root = ET.fromstring(text.encode("utf-8"))
    items = []
    for it in root.iter("item"):
        g = lambda tag: (it.findtext(tag) or "").strip()  # noqa: E731
        items.append({"title": strip_html(g("title")), "url": g("link"), "summary": strip_html(g("description"))[:400],
                      "time": parse_time(g("pubDate"))})
    return items


def fetch_html(src):
    text = I.http_get(src["url"], as_json=False, timeout=25, retries=2)
    pat = re.compile(r'<a[^>]+href="(' + src.get("link_pattern", r"[^\"]+") + r')"[^>]*>(.*?)</a>', re.S)
    seen, items = set(), []
    for url, inner in pat.findall(text):
        title = strip_html(inner)
        if not title:  # some sites keep the headline in the URL slug
            title = I.norm(url.rstrip("/").split("/")[-1].replace("-", " "))
            import urllib.parse
            title = urllib.parse.unquote(title).replace("-", " ")
        if url in seen or len(title) < 12:
            continue
        seen.add(url)
        items.append({"title": title, "url": url, "summary": "", "time": None})
    return items[:60]


def site_news(cfg, errors):
    out = []
    for src in cfg.get("news_sources") or []:
        try:
            items = fetch_rss(src) if src.get("type", "rss") == "rss" else fetch_html(src)
            import urllib.parse
            for it in items:
                it["source"] = src["name"]
                it["url"] = urllib.parse.unquote(it["url"] or "") or None
            out += items
        except Exception as e:  # one dead site must not kill the briefing
            errors.append(f"{src.get('name')}: {e}")
    return out


def matcher(sym: str, name: str):
    """A headline is about a symbol when the symbol is quoted («فولاد», (فولاد), نماد فولاد, #فولاد)
    or the company's name appears. Bare words are not enough: many symbols are ordinary words
    (فولاد = steel, جم, فارس, خودرو, کالا...)."""
    s = I.norm(sym)
    pats = [r"(?:نماد\s*|«|\(|#)" + re.escape(s) + r"(?:»|\)|\s|$|،|\.)"]
    n = I.norm(name)
    for pre in ("شرکت ", "گروه ", "سرمایه گذاری ", "سرمایهگذاری ", "صنایع "):
        n = n.replace(pre, "")
    words = n.split()
    if len(words) >= 3:
        n = " ".join(words[:2])           # «فولاد مبارکه» rather than «فولاد مبارکه اصفهان»
    if len(n) >= 8 and len(n.split()) >= 2:
        pats.append(re.escape(n))
    rx = re.compile("|".join(pats))
    return lambda text: bool(rx.search(I.norm(text)))


def targets(a, cfg):
    if a.symbols:
        return [I.resolve(s) for s in a.symbols]
    w = I.read_json("watchlist.json", {}) or {}
    pos = (I.read_json("positions.json", {}) or {}).get("open", [])
    syms = list(dict.fromkeys(list(w.get("manual", [])) + [p["symbol"] for p in pos] +
                              [r["symbol"] for r in (w.get("symbols") or [])[: a.top]]))
    if not syms:
        I.die("نمادی برای بررسی نیست: نماد بدهید (news.py check فولاد) یا اول اسکنر را اجرا کنید.")
    return [I.resolve(s) for s in syms]


def key(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]


def cmd_check(a):
    cfg = I.config()
    seen = I.read_json("news_seen.json", {}) or {}
    since = I.now_tehran() - dt.timedelta(hours=a.hours)
    syms = targets(a, cfg)
    errors, items = [], []

    for s in syms:
        try:
            for l in I.codal(s["symbol"]):
                t = I.parse_jdatetime(l["published"])
                items.append({"k": key("codal", l["id"]), "source": "کدال", "symbol": s["symbol"], "title": l["title"],
                              "url": l["url"], "time": t, "official": True})
        except I.IranError as e:
            errors.append(f"کدال {s['symbol']}: {e}")
        try:
            for m in I.messages(s["insCode"], 5):
                t = dt.datetime.combine(I.deven_to_date(m["date"]), I.heven_to_time(m["time"]), I.TEHRAN)
                items.append({"k": key("msg", m["id"]), "source": "پیام ناظر", "symbol": s["symbol"],
                              "title": m["title"], "summary": m["text"][:300], "time": t, "official": True})
        except I.IranError as e:
            errors.append(f"پیام ناظر {s['symbol']}: {e}")

    match = [(s["symbol"], matcher(s["symbol"], s.get("name", ""))) for s in syms]
    market = []
    for it in site_news(cfg, errors):
        text = it["title"] + " " + it.get("summary", "")
        hit = [sym for sym, f in match if f(text)]
        base = {"k": key("site", it["url"] or it["title"]), "source": it["source"], "title": it["title"],
                "url": it["url"], "summary": it.get("summary"), "time": it["time"], "official": False}
        if hit:
            for sym in hit:
                items.append(base | {"symbol": sym, "k": base["k"] + sym})
        elif a.market:
            market.append(base | {"symbol": None})

    def fresh(it):
        if not a.all_seen and it["k"] in seen:
            return False
        return it["time"] is None or it["time"] >= since

    new = [it for it in items if fresh(it)]
    new_market = [it for it in market if fresh(it)]
    order = lambda it: it["time"] or I.now_tehran()  # noqa: E731
    new.sort(key=order, reverse=True)
    new_market.sort(key=order, reverse=True)

    # price context
    moves = {}
    for s in syms:
        if any(it["symbol"] == s["symbol"] for it in new):
            try:
                q = I.quote(s["insCode"])
                moves[s["symbol"]] = q
            except I.IranError:
                pass

    st = I.market_status(cfg)
    print(f"اخبار {st['jalali']} — {len(syms)} نماد: {'، '.join(s['symbol'] for s in syms)}")
    if not new:
        print(f"\nخبر تازه‌ای در {a.hours} ساعت گذشته برای این نمادها نیست.")
    by_sym = {}
    for it in new:
        by_sym.setdefault(it["symbol"], []).append(it)
    for sym, its in by_sym.items():
        q = moves.get(sym)
        mv = ""
        if q:
            mv = f"  آخرین {I.price(q['last'])} ({q['chg_pct']:+}%)" if q.get("chg_pct") is not None else ""
            if q.get("queue"):
                mv += "  [صف خرید]" if q["queue"] == "buy_queue" else "  [صف فروش]"
            if q.get("state_code") and q["state_code"] != "A":
                mv += f"  وضعیت: {q['state']}"
        print(f"\n■ {sym}{mv}")
        for it in its:
            tg = tags_for(it["title"] + " " + (it.get("summary") or ""))
            when = it["time"].strftime("%H:%M ") + I.jdate(it["time"].date()) if it["time"] else "—"
            flag = "★" if it["official"] else "·"
            print(f"  {flag} [{when}] [{it['source']}] [{LABEL[tg[0]]}] {it['title']}")
            if it.get("url"):
                print(f"      {it['url']}")
    if a.market and new_market:
        print(f"\n■ تیترهای بازار ({len(new_market)})")
        for it in new_market[: a.market_limit]:
            when = it["time"].strftime("%H:%M") if it["time"] else "—"
            print(f"  · [{when}] [{it['source']}] {it['title']}")
            if it.get("url"):
                print(f"      {it['url']}")
    if errors:
        print("\nمنابعی که جواب ندادند: " + " | ".join(errors))
    print("\n★ = رسمی (کدال / ناظر بازار)   · = سایت خبری؛ قبل از تصمیم، خبر را در کدال تایید کنید.")

    for it in new + new_market:
        seen[it["k"]] = I.today_key()
    cutoff = (I.now_tehran() - dt.timedelta(days=30)).strftime("%Y-%m-%d")
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    I.write_json("news_seen.json", seen)
    I.write_json("news_last.json", {"checked_at": st["now"], "symbols": [s["symbol"] for s in syms],
                                    "items": [{k: (v.isoformat() if isinstance(v, dt.datetime) else v)
                                               for k, v in it.items()} for it in new]})


def cmd_codal(a):
    s = I.resolve(a.symbol)
    for p in range(1, a.pages + 1):
        for l in I.codal(s["symbol"], page=p):
            print(f"[{I.norm(l['published'])}] {l['code']}  {l['title']}\n    {l['url']}")


def cmd_sources(a):
    for s in I.config().get("news_sources") or []:
        print(f"{s['name']:<12} {s.get('type','rss'):<5} {s['url']}")
    print("\nبرای افزودن یا حذف، trader/config.json → news_sources را ویرایش کنید.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    c = sp.add_parser("check")
    c.add_argument("symbols", nargs="*")
    c.add_argument("--top", type=int, default=15)
    c.add_argument("--market", action="store_true")
    c.add_argument("--market-limit", type=int, default=25)
    c.add_argument("--hours", type=float, default=48)
    c.add_argument("--all-seen", action="store_true", help="show items already shown before")
    d = sp.add_parser("codal")
    d.add_argument("symbol")
    d.add_argument("--pages", type=int, default=1)
    sp.add_parser("sources")
    sp.add_parser("reset")
    a = p.parse_args()
    if a.cmd == "check":
        cmd_check(a)
    elif a.cmd == "codal":
        cmd_codal(a)
    elif a.cmd == "sources":
        cmd_sources(a)
    else:
        I.write_json("news_seen.json", {})
        print("حافظه اخبار پاک شد.")


if __name__ == "__main__":
    I.run(main)
