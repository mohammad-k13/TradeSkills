"""Shared library for the iran-* trading skills (Tehran Stock Exchange + Fara Bourse).

Stdlib only. Prices from TSETMC are in RIAL; everything is stored in Rial and shown in
Toman (Rial / 10) unless config "display_currency" is "rial".

Data sources (all public, no login):
  TSETMC  https://cdn.tsetmc.com/api/...   prices, order book, real/legal flow, band, messages
  Codal   https://search.codal.ir/api/...  company announcements (اطلاعیه‌ها و صورت‌های مالی)
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------- console
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) iran-trader/1.0"
TSE = "https://cdn.tsetmc.com/api"
CODAL = "https://search.codal.ir/api/search/v2/q"
CODAL_WEB = "https://codal.ir"

# ---------------------------------------------------------------- paths
SKILLS_DIR = Path(__file__).resolve().parent.parent          # .../iran-trader/skills
HOME = Path(os.environ.get("IRAN_TRADER_HOME") or SKILLS_DIR.parent / "trader")
CACHE = HOME / "cache"


class IranError(Exception):
    """A plain-language failure the skill should show the user as-is."""


def path(name: str) -> Path:
    HOME.mkdir(parents=True, exist_ok=True)
    return HOME / name


def read_json(name: str, default=None):
    p = path(name) if not isinstance(name, Path) else name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(name, data) -> Path:
    p = path(name) if not isinstance(name, Path) else name
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    return p


# ---------------------------------------------------------------- config
DEFAULT_CONFIG = {
    "display_currency": "toman",          # toman | rial
    # account and limits (amounts in TOMAN, like brokers show)
    "cash_toman": None,                   # your buying power; set it with budget.py rules
    "max_loss_per_trade_toman": None,     # e.g. 2_000_000
    "max_daily_loss_toman": None,         # total open risk allowed per day
    "max_position_pct": 25.0,             # one stock at most this % of cash
    "max_order_toman": None,              # hard cap on one order's value
    "cash_buffer_pct": 10.0,              # keep this % of cash untouched
    "min_reward_risk": 1.5,
    "max_trades_per_day": 3,
    "max_orders_per_day": 10,
    "blocked_symbols": [],
    "allow_base_market": False,           # بازار پایه (yVal 309/313): thin, risky
    "allow_rights": False,                # حق تقدم
    "allow_under_supervision": False,     # نمادهای تحت احتیاط / زیر نظر
    # fees (fractions). TSE stock defaults; check your broker's sheet (کارمزد)
    "fee_buy": 0.003712,
    "fee_sell": 0.0088,                   # includes the 0.5% sale tax
    "tick_rial": 1,                       # 1 Rial is valid on every symbol; many trade in 10s
    "band_pct": 0.03,                     # usual daily limit (دامنه نوسان); live data always wins
    # session (Tehran time, UTC+03:30, no DST)
    "session_open": "09:00",
    "session_close": "12:30",
    "entry_window": ["09:00", "12:00"],
    "trading_weekdays": [5, 6, 0, 1, 2],  # Sat Sun Mon Tue Wed (Python weekday numbers)
    # fixed solar holidays (month-day, Jalali). Lunar holidays move every year:
    # add them to "holidays_jalali" as "1405-09-05" etc.
    "fixed_holidays_md": ["01-01", "01-02", "01-03", "01-04", "01-12", "01-13",
                           "03-14", "03-15", "11-22", "12-29"],
    "holidays_jalali": [],
    # scanner
    "scan_min_value_toman": 2_000_000_000,   # min value traded today
    "scan_daily_top": 150,                   # how many liquid symbols get full daily history
    # news
    "news_sources": [                        # type rss | html (html: link_pattern regex on <a href>)
        {"name": "سنا", "url": "https://www.sena.ir/rss", "type": "rss"},
        {"name": "بورس‌نیوز", "url": "https://www.boursenews.ir/fa/rss/allnews", "type": "rss"},
        {"name": "نبض بورس", "url": "https://www.nabzebourse.com/fa/rss/allnews", "type": "rss"},
        {"name": "شهر بورس", "url": "https://shahrebours.com/feed/", "type": "rss"},
        {"name": "اقتصادنیوز", "url": "https://www.eghtesadnews.com/feeds/", "type": "rss"},
        {"name": "بورس۲۴", "url": "https://www.bourse24.ir/news", "type": "html",
         "link_pattern": r"https://www\.bourse24\.ir/news/\d+/[^\"']+"},
    ],
    # Telegram signal channels (public channels only, read via https://t.me/s/<name>)
    "signal_channels": [],
    # paper = demo account with fake money on real prices (trader/paper.json); live = real broker
    "mode": "paper",
    "paper_start_cash_toman": 3_500_000,
    "paper_auto_exits": True,             # paper: sell automatically when the stop or target trades
    # broker (browser automation through Chrome; you log in yourself)
    "broker_name": "ایزی‌تریدر (مفید)",
    "broker_url": "https://d.easytrader.ir/",
}


def config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(read_json("config.json", {}) or {})
    return cfg


def save_config(cfg: dict) -> Path:
    return write_json("config.json", cfg)


# ---------------------------------------------------------------- text
_AR = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه", "‌": "", "‏": "",
                     "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4", "۵": "5", "۶": "6",
                     "۷": "7", "۸": "8", "۹": "9", "٠": "0", "١": "1", "٢": "2", "٣": "3",
                     "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9"})


def norm(s) -> str:
    """Normalize Arabic/Persian letters and digits so 'فولاد' from any source matches."""
    return re.sub(r"\s+", " ", str(s or "").translate(_AR)).strip()


def fa(s) -> str:
    """Display form: Persian ی/ک (TSETMC sends Arabic ي/ك)."""
    return str(s or "").replace("ي", "ی").replace("ك", "ک").strip()


# ---------------------------------------------------------------- money
def toman(rial: float) -> float:
    return rial / 10.0


def money(rial, cfg=None) -> str:
    """Format a RIAL amount for display in the user's currency."""
    if rial is None:
        return "-"
    cur = (cfg or config()).get("display_currency", "toman")
    v = rial / 10.0 if cur == "toman" else rial
    unit = "تومان" if cur == "toman" else "ریال"
    a = abs(v)
    if a >= 1e12:
        s = f"{v/1e12:,.2f} هزار میلیارد"
    elif a >= 1e9:
        s = f"{v/1e9:,.2f} میلیارد"
    elif a >= 1e6:
        s = f"{v/1e6:,.2f} میلیون"
    else:
        s = f"{v:,.0f}"
    return f"{s} {unit}"


def price(rial) -> str:
    """Share prices are quoted in Rial on the exchange; show them that way (as TSETMC does)."""
    return "-" if rial is None else f"{rial:,.0f}"


def fees(cfg=None):
    c = cfg or config()
    return float(c["fee_buy"]), float(c["fee_sell"])


# ---------------------------------------------------------------- calendar
TEHRAN = dt.timezone(dt.timedelta(hours=3, minutes=30), "Asia/Tehran")


def now_tehran() -> dt.datetime:
    fake = os.environ.get("IRAN_TRADER_NOW")  # "2026-11-09 10:15" for testing
    if fake:
        return dt.datetime.strptime(fake, "%Y-%m-%d %H:%M").replace(tzinfo=TEHRAN)
    return dt.datetime.now(TEHRAN)


def g2j(gy: int, gm: int, gd: int):
    """Gregorian -> Jalali (algorithm from jdf / Borkowski)."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return jy, jm, jd


def j2g(jy: int, jm: int, jd: int):
    jy += 1595
    days = -355668 + (365 * jy) + ((jy // 33) * 8) + (((jy % 33) + 3) // 4) + jd
    days += (jm - 1) * 31 if jm < 7 else ((jm - 7) * 30) + 186
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    sal = [0, 31, 29 if (gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 1
    while gm <= 12 and gd > sal[gm]:
        gd -= sal[gm]
        gm += 1
    return gy, gm, gd


def jdate(d) -> str:
    """date / datetime / 20261109 int -> '1405/08/18'."""
    if isinstance(d, int) or (isinstance(d, str) and d.isdigit()):
        s = str(d)
        d = dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    y, m, dd = g2j(d.year, d.month, d.day)
    return f"{y:04d}/{m:02d}/{dd:02d}"


def parse_jdatetime(s: str):
    """'۱۴۰۵/۰۸/۱۸ ۱۳:۰۷:۳۳' -> aware datetime (Tehran)."""
    s = norm(s)
    m = re.match(r"(\d{4})/(\d{1,2})/(\d{1,2})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?", s)
    if not m:
        return None
    y, mo, d = (int(x) for x in m.group(1, 2, 3))
    gy, gm, gd = j2g(y, mo, d)
    hh, mm, ss = int(m.group(4) or 0), int(m.group(5) or 0), int(m.group(6) or 0)
    return dt.datetime(gy, gm, gd, hh, mm, ss, tzinfo=TEHRAN)


def deven_to_date(n) -> dt.date:
    s = str(int(n))
    return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def heven_to_time(n) -> dt.time:
    s = f"{int(n):06d}"
    return dt.time(int(s[:2]), int(s[2:4]), int(s[4:6]))


def _hm(s: str) -> dt.time:
    h, m = s.split(":")
    return dt.time(int(h), int(m))


def is_holiday(d: dt.date, cfg=None) -> str | None:
    c = cfg or config()
    y, m, dd = g2j(d.year, d.month, d.day)
    if f"{m:02d}-{dd:02d}" in c["fixed_holidays_md"]:
        return "تعطیل رسمی"
    if f"{y:04d}-{m:02d}-{dd:02d}" in c["holidays_jalali"]:
        return "تعطیل (فهرست شما)"
    if d.weekday() not in c["trading_weekdays"]:
        return "آخر هفته"
    return None


def market_status(cfg=None, t: dt.datetime | None = None) -> dict:
    """Is the market open now? Uses the calendar; skills confirm with live data where it matters."""
    c = cfg or config()
    t = t or now_tehran()
    o, cl = _hm(c["session_open"]), _hm(c["session_close"])
    hol = is_holiday(t.date(), c)
    st = {"now": t.strftime("%Y-%m-%d %H:%M"), "jalali": jdate(t.date()) + t.strftime(" %H:%M"),
          "open_time": c["session_open"], "close_time": c["session_close"]}
    if hol:
        st.update(open=False, state="closed", reason=hol)
    elif t.time() < o:
        st.update(open=False, state="pre_open", reason=f"بازار ساعت {c['session_open']} باز می‌شود")
    elif t.time() >= cl:
        st.update(open=False, state="closed", reason=f"بازار ساعت {c['session_close']} بسته شد")
    else:
        st.update(open=True, state="open", reason="بازار باز است")
    ew = c["entry_window"]
    st["in_entry_window"] = bool(st["open"] and _hm(ew[0]) <= t.time() < _hm(ew[1]))
    return st


def next_session(cfg=None, t=None) -> dt.date:
    c = cfg or config()
    t = t or now_tehran()
    d = t.date()
    if t.time() >= _hm(c["session_open"]) or is_holiday(d, c):
        d += dt.timedelta(days=1)
    while is_holiday(d, c):
        d += dt.timedelta(days=1)
    return d


# ---------------------------------------------------------------- http
def http_get(url: str, timeout=25, retries=3, as_json=True, headers=None):
    last = None
    h = {"User-Agent": UA, "Accept": "application/json, text/html;q=0.9, */*;q=0.8"}
    h.update(headers or {})
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
                raw = r.read()
                ctype = r.headers.get_content_charset() or "utf-8"
            text = raw.decode(ctype, errors="replace")
            return json.loads(text) if as_json else text
        except Exception as e:  # network blips are common on TSETMC around the open
            last = e
            time.sleep(1.0 + i)
    raise IranError(f"could not reach {url.split('?')[0]}: {last}")


def tse(path_: str, **kw):
    return http_get(f"{TSE}/{path_}", **kw)


# ---------------------------------------------------------------- symbols
SHARE_YVALS = {300, 303}            # بورس، فرابورس
BASE_YVALS = {309, 313}             # بازار پایه


def _symbols_cache() -> dict:
    return read_json(CACHE / "symbols.json", {}) or {}


def resolve(symbol: str) -> dict:
    """Symbol (نماد, e.g. 'فولاد') -> {'insCode', 'symbol', 'name', 'flow', ...}."""
    key = norm(symbol)
    if key.isdigit() and len(key) > 10:
        return {"insCode": key, "symbol": key, "name": key}
    cache = _symbols_cache()
    if key in cache:
        return cache[key]
    data = tse(f"Instrument/GetInstrumentSearch/{urllib.parse.quote(key)}")
    hits = data.get("instrumentSearch") or []
    exact = [h for h in hits if norm(h.get("lVal18AFC")) == key]
    live = [h for h in exact if h.get("lastDate") in (0, None, 1) or True]
    if not live:
        sugg = ", ".join(fa(h.get("lVal18AFC")) for h in hits[:6])
        raise IranError(f"نماد «{symbol}» پیدا نشد." + (f" شاید منظورتان: {sugg}" if sugg else ""))
    # prefer the main-board instrument (flow 1/2, not a closed duplicate)
    live.sort(key=lambda h: (h.get("flow") not in (1, 2), h.get("lastDate") not in (0, 1)))
    h = live[0]
    info = {"insCode": h["insCode"], "symbol": fa(h["lVal18AFC"]), "name": fa(h.get("lVal30")),
            "flow": h.get("flow"), "flowTitle": h.get("flowTitle"), "board": h.get("cgrValCot")}
    cache[key] = info
    write_json(CACHE / "symbols.json", cache)
    return info


# ---------------------------------------------------------------- quotes
def quote(ins: str) -> dict:
    """Live snapshot: last, close, yesterday, band, state, order book top level, flow."""
    cpi = tse(f"ClosingPrice/GetClosingPriceInfo/{ins}")["closingPriceInfo"]
    info = tse(f"Instrument/GetInstrumentInfo/{ins}")["instrumentInfo"]
    bl = tse(f"BestLimits/{ins}").get("bestLimits") or []
    st = cpi.get("instrumentState") or {}
    band = info.get("staticThreshold") or {}
    q = {
        "insCode": ins,
        "symbol": fa(info.get("lVal18AFC")),
        "name": fa(info.get("lVal30")),
        "yVal": int(info.get("yVal") or 0),
        "sector": fa((info.get("sector") or {}).get("lSecVal")),
        "date": int(cpi.get("finalLastDate") or cpi.get("dEven") or 0),
        "time": int(cpi.get("hEven") or 0),
        "last": float(cpi.get("pDrCotVal") or 0),
        "close": float(cpi.get("pClosing") or 0),
        "yesterday": float(cpi.get("priceYesterday") or 0),
        "open": float(cpi.get("priceFirst") or 0),
        "high": float(cpi.get("priceMax") or 0),
        "low": float(cpi.get("priceMin") or 0),
        "volume": float(cpi.get("qTotTran5J") or 0),
        "value": float(cpi.get("qTotCap") or 0),
        "trades": int(cpi.get("zTotTran") or 0),
        "band_max": float(band.get("psGelStaMax") or 0),
        "band_min": float(band.get("psGelStaMin") or 0),
        "state_code": (st.get("cEtaval") or "").strip(),
        "state": fa(st.get("cEtavalTitle")),
        "under_supervision": int(info.get("underSupervision") or st.get("underSupervision") or 0),
        "eps": (info.get("eps") or {}).get("estimatedEPS"),
        "sector_pe": (info.get("eps") or {}).get("sectorPE"),
        "shares_out": info.get("zTitad"),
        "base_volume": info.get("baseVol"),
        "avg_volume_30d": info.get("qTotTran5JAvg"),
        "week_high": info.get("maxWeek"), "week_low": info.get("minWeek"),
        "year_high": info.get("maxYear"), "year_low": info.get("minYear"),
        "book": [{"bid": l.get("pMeDem"), "bid_vol": l.get("qTitMeDem"), "bid_n": l.get("zOrdMeDem"),
                  "ask": l.get("pMeOf"), "ask_vol": l.get("qTitMeOf"), "ask_n": l.get("zOrdMeOf")} for l in bl],
    }
    q["queue"] = queue_state(q)
    q["chg_pct"] = pct(q["last"], q["yesterday"])
    q["close_pct"] = pct(q["close"], q["yesterday"])
    return q


def queue_state(q: dict) -> str:
    """'buy_queue' (صف خرید), 'sell_queue' (صف فروش) or ''."""
    b = (q.get("book") or [{}])[0] if q.get("book") else {}
    bid, ask = b.get("bid") or 0, b.get("ask") or 0
    bvol, avol = b.get("bid_vol") or 0, b.get("ask_vol") or 0
    hi, lo = q.get("band_max") or 0, q.get("band_min") or 0
    if hi and bid >= hi and bvol > 0 and avol == 0:
        return "buy_queue"
    if lo and ask and ask <= lo and avol > 0 and bvol == 0:
        return "sell_queue"
    return ""


def pct(a, b):
    return round((a / b - 1) * 100, 2) if a and b else None


def client_type(ins: str) -> dict:
    """Today's real (حقیقی) vs legal (حقوقی) buy/sell."""
    c = tse(f"ClientType/GetClientType/{ins}/1/0").get("clientType") or {}
    return flow_metrics(c)


def flow_metrics(c: dict, price_rial: float | None = None) -> dict:
    bi, si = float(c.get("buy_I_Volume") or 0), float(c.get("sell_I_Volume") or 0)
    bn, sn = float(c.get("buy_N_Volume") or 0), float(c.get("sell_N_Volume") or 0)
    nbi, nsi = int(c.get("buy_CountI") or 0), int(c.get("sell_CountI") or 0)
    out = {"buy_real_vol": bi, "sell_real_vol": si, "buy_legal_vol": bn, "sell_legal_vol": sn,
           "buy_real_n": nbi, "sell_real_n": nsi,
           "real_net_vol": bi - si}
    # قدرت خریدار حقیقی: per-capita buy / per-capita sell
    if nbi and nsi and si:
        out["real_power"] = round((bi / nbi) / (si / nsi), 2)
    else:
        out["real_power"] = None
    if price_rial:
        out["real_net_value"] = (bi - si) * price_rial
        out["per_capita_buy"] = bi * price_rial / nbi if nbi else None
        out["per_capita_sell"] = si * price_rial / nsi if nsi else None
    return out


def messages(ins: str, limit=10) -> list:
    """Exchange / watchdog messages (پیام ناظر): halts, reopenings, warnings."""
    m = tse(f"Msg/GetMsgByInsCode/{ins}").get("msg") or []
    return [{"id": x.get("tseMsgIdn"), "date": x.get("dEven"), "time": x.get("hEven"),
             "title": fa(x.get("tseTitle")), "text": fa(x.get("tseDesc"))} for x in m[:limit]]


# ---------------------------------------------------------------- history
def daily(ins: str, days=0, adjust=True, use_cache=True) -> list[dict]:
    """Daily bars oldest -> newest. adjust=True back-adjusts for capital raises and dividends
    (TSETMC's 'yesterday' price on the ex-date is the adjusted reference)."""
    today = now_tehran().strftime("%Y%m%d")
    cf = CACHE / "daily" / f"{ins}.json"
    raw = None
    if use_cache:
        c = read_json(cf)
        if c and c.get("fetched") == today and (days == 0 or len(c["bars"]) >= days or c.get("all")):
            raw = c["bars"]
    if raw is None:
        n = 0 if days == 0 else max(days, 60)
        raw = tse(f"ClosingPrice/GetClosingPriceDailyList/{ins}/{n}").get("closingPriceDaily") or []
        write_json(cf, {"fetched": today, "all": n == 0, "bars": raw})
    rows = [{"date": int(r["dEven"]), "open": float(r["priceFirst"]), "high": float(r["priceMax"]),
             "low": float(r["priceMin"]), "close": float(r["pClosing"]), "last": float(r["pDrCotVal"]),
             "yesterday": float(r["priceYesterday"]), "volume": float(r["qTotTran5J"]),
             "value": float(r["qTotCap"]), "trades": int(r["zTotTran"])}
            for r in raw if float(r.get("qTotTran5J") or 0) > 0]
    rows.sort(key=lambda r: r["date"])
    if adjust and rows:
        f = 1.0
        for i in range(len(rows) - 1, 0, -1):
            cur, prev = rows[i], rows[i - 1]
            for k in ("open", "high", "low", "close", "last", "yesterday"):
                cur[k] *= f
            if prev["close"] and cur["yesterday"] and abs(cur["yesterday"] / f - prev["close"]) > 1.0:
                f *= (cur["yesterday"] / f) / prev["close"]
                cur["adjusted_event"] = True
        for k in ("open", "high", "low", "close", "last", "yesterday"):
            rows[0][k] *= f
    if days:
        rows = rows[-days:]
    return rows


def trades_today(ins: str) -> list[dict]:
    t = tse(f"Trade/GetTrade/{ins}").get("trade") or []
    return [{"time": int(x["hEven"]), "price": float(x["pTran"]), "qty": float(x["qTitTran"])}
            for x in t if not x.get("canceled")]


def trades_on(ins: str, deven: int) -> list[dict]:
    t = tse(f"Trade/GetTradeHistory/{ins}/{deven}/false").get("tradeHistory") or []
    return [{"time": int(x["hEven"]), "price": float(x["pTran"]), "qty": float(x["qTitTran"])}
            for x in t if not x.get("canceled")]


def bars_from_trades(trades: list[dict], minutes=5, start="09:00") -> list[dict]:
    """Group trades into N-minute OHLCV bars starting at the session open."""
    if not trades:
        return []
    st = _hm(start)
    st_s = st.hour * 3600 + st.minute * 60
    bars: dict[int, dict] = {}
    for tr in sorted(trades, key=lambda x: x["time"]):
        t = heven_to_time(tr["time"])
        secs = t.hour * 3600 + t.minute * 60 + t.second
        if secs < st_s:
            continue
        k = (secs - st_s) // (minutes * 60)
        b = bars.get(k)
        p, q = tr["price"], tr["qty"]
        if b is None:
            s0 = st_s + k * minutes * 60
            bars[k] = {"start": f"{s0//3600:02d}:{(s0%3600)//60:02d}", "open": p, "high": p, "low": p,
                       "close": p, "volume": q}
        else:
            b["high"], b["low"], b["close"] = max(b["high"], p), min(b["low"], p), p
            b["volume"] += q
    return [bars[k] for k in sorted(bars)]


# ---------------------------------------------------------------- market-wide
def market_watch() -> list[dict]:
    """One request: every instrument with last/close/band/order book (دیده‌بان بازار)."""
    url = ("ClosingPrice/GetMarketWatch?market=0&industrialGroup=&paperTypes%5B0%5D=1&paperTypes%5B1%5D=2"
           "&paperTypes%5B2%5D=8&showTraded=false&withBestLimits=true")
    return tse(url, timeout=60).get("marketwatch") or []


def universe(max_age_days=3) -> dict:
    """{normalized symbol: {'symbol', 'insCode', 'name', 'yVal'}} for every share, cached."""
    c = read_json(CACHE / "universe.json")
    if c and c.get("date", "") >= (now_tehran() - dt.timedelta(days=max_age_days)).strftime("%Y-%m-%d"):
        return c["symbols"]
    out = {}
    for x in market_watch():
        y = int(x.get("yVal") or 0)
        if y in SHARE_YVALS | BASE_YVALS and x.get("lva") and not norm(x["lva"])[-1].isdigit():
            out[norm(x["lva"])] = {"symbol": fa(x["lva"]), "insCode": x["insCode"], "name": fa(x.get("lvc")), "yVal": y}
    write_json(CACHE / "universe.json", {"date": now_tehran().strftime("%Y-%m-%d"), "symbols": out})
    return out


def client_type_all() -> dict:
    rows = tse("ClientType/GetClientTypeAll", timeout=60).get("clientTypeAllDto") or []
    return {r["insCode"]: r for r in rows}


def is_share(sym: str, yval: int, cfg=None) -> bool:
    c = cfg or config()
    s = norm(sym)
    if not s or s[-1].isdigit():          # فولاد3, ... = block / other boards
        return False
    ok = set(SHARE_YVALS)
    if c.get("allow_base_market"):
        ok |= BASE_YVALS
    return yval in ok


# ---------------------------------------------------------------- codal
def codal(symbol: str | None = None, page=1, extra: dict | None = None) -> list[dict]:
    params = {"PageNumber": page}
    if symbol:
        params["Symbol"] = fa(symbol)
    params.update(extra or {})
    d = http_get(CODAL + "?" + urllib.parse.urlencode(params))
    out = []
    for l in d.get("Letters") or []:
        out.append({"id": l.get("TracingNo"), "symbol": fa(l.get("Symbol")), "company": fa(l.get("CompanyName")),
                    "title": fa(l.get("Title")), "code": norm(l.get("LetterCode")),
                    "published": l.get("PublishDateTime"),
                    "url": CODAL_WEB + l["Url"] if l.get("Url") else None,
                    "pdf": (CODAL_WEB + "/Reports/" + l["PdfUrl"]) if l.get("PdfUrl") else None})
    return out


# ---------------------------------------------------------------- indicators
def sma(xs, n):
    return sum(xs[-n:]) / n if len(xs) >= n else None


def rsi(closes, n=14):
    if len(closes) <= n:
        return None
    gains = losses = 0.0
    for a, b in zip(closes[-n - 1:-1], closes[-n:]):
        d = b - a
        gains += max(d, 0)
        losses += max(-d, 0)
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return round(100 - 100 / (1 + rs), 1)


def atr(bars, n=14):
    if len(bars) <= n:
        return None
    trs = []
    for p, b in zip(bars[-n - 1:-1], bars[-n:]):
        trs.append(max(b["high"] - b["low"], abs(b["high"] - p["close"]), abs(b["low"] - p["close"])))
    return sum(trs) / n


def band_pct(q: dict) -> float:
    """Today's daily price limit as a fraction (e.g. 0.03 for ±3%)."""
    if q.get("band_max") and q.get("yesterday"):
        return round(q["band_max"] / q["yesterday"] - 1, 4)
    return 0.03


def round_tick(p: float, cfg=None, down=True) -> float:
    t = float((cfg or config()).get("tick_rial") or 1)
    import math
    return (math.floor(p / t) if down else math.ceil(p / t)) * t


# ---------------------------------------------------------------- account (paper or live)
def is_paper(cfg=None) -> bool:
    return (cfg or config()).get("mode", "paper") == "paper"


def paper_state() -> dict | None:
    return read_json("paper.json")


def account_cash_rial(cfg=None):
    """Cash available for a new buy: the paper account's free cash in paper mode, else cash_toman."""
    c = cfg or config()
    if is_paper(c):
        p = paper_state()
        if p is None:
            return c["paper_start_cash_toman"] * 10
        reserved = sum(o["reserve_rial"] for o in p["orders"] if o["status"] == "open" and o["side"] == "buy")
        return p["cash_rial"] - reserved
    return c["cash_toman"] * 10 if c.get("cash_toman") else None


def account_equity_rial(cfg=None):
    """Size limits (position %, buffer) are taken against total equity, not just free cash."""
    c = cfg or config()
    if is_paper(c):
        p = paper_state()
        if p is None:
            return c["paper_start_cash_toman"] * 10
        return p.get("last_equity_rial") or p["cash_rial"]
    return c["cash_toman"] * 10 if c.get("cash_toman") else None


def open_positions(cfg=None) -> list[dict]:
    c = cfg or config()
    if is_paper(c):
        return (paper_state() or {}).get("positions", [])
    return (read_json("positions.json", {}) or {}).get("open", [])


# ---------------------------------------------------------------- misc
def order_hash(o: dict) -> str:
    keys = ("symbol", "side", "qty", "price", "stop", "target")
    s = json.dumps({k: o.get(k) for k in keys}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]


def today_key() -> str:
    return now_tehran().strftime("%Y-%m-%d")


def die(msg: str, code=2):
    print(f"✖ {msg}")
    sys.exit(code)


def run(main):
    """Wrap a CLI main(): IranError -> plain message, exit 2."""
    try:
        main()
    except IranError as e:
        die(str(e))
    except KeyboardInterrupt:
        die("stopped", 130)
