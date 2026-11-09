"""Paper-trading dashboard: a local web page for the demo account, on real TSETMC prices.

  python dashboard.py [--port 8765] [--no-browser]

Opens http://127.0.0.1:8765. Only this computer can reach it. Every order from the page goes
through the same /iran-risk check as the chat (no bypass), then into the paper account.
During the session the account is updated against real trades every 30 seconds.
"""
from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parent
sys.path.insert(0, str(SKILLS / "iran-common"))
sys.path.insert(0, str(SKILLS / "iran-risk"))
sys.path.insert(0, str(HERE))
import iran as I  # noqa: E402
import paper as P  # noqa: E402
import risk as R  # noqa: E402

TOKEN = secrets.token_urlsafe(16)
LOCK = threading.Lock()
STATUS = {"last_update": None, "last_error": None, "scan_running": False, "scan_msg": None}


# ---------------------------------------------------------------- helpers
def safe_update():
    with LOCK:
        try:
            ev = P.update()
            STATUS["last_update"] = I.market_status()["now"]
            STATUS["last_error"] = None
            return ev
        except Exception as e:  # network trouble must not kill the server
            STATUS["last_error"] = str(e)
            return []


def updater():
    safe_update()
    while True:
        time.sleep(30)
        st = I.market_status()
        if st["open"] or st["state"] == "pre_open":
            safe_update()


def state():
    cfg = I.config()
    p = P.load()
    fb, fs = I.fees(cfg)
    s = P.stats(p)
    st = I.market_status(cfg)
    st["next_session"] = I.jdate(I.next_session(cfg))
    positions = []
    open_risk = 0
    for x in p["positions"]:
        last = x.get("last") or x["avg_price"]
        value = x["qty"] * last * (1 - fs)
        pnl = value - x["cost_rial"]
        risk_now = max(0, x["qty"] * (last - x["stop"])) if x.get("stop") else None
        open_risk += risk_now or 0
        positions.append(x | {"value_rial": round(value), "pnl_rial": round(pnl),
                              "pnl_pct": pnl / x["cost_rial"] * 100 if x["cost_rial"] else 0,
                              "to_stop_pct": (x["stop"] / last - 1) * 100 if x.get("stop") else None,
                              "to_target_pct": (x["target"] / last - 1) * 100 if x.get("target") else None,
                              "risk_now_rial": risk_now})
    today = I.today_key()
    eq_today = [e for e in p["equity"] if e["t"][:10] == today]
    prev = [e for e in p["equity"] if e["t"][:10] < today]
    base = prev[-1]["equity"] if prev else p["start_cash_rial"]
    w = I.read_json("watchlist.json", {}) or {}
    watch = [{k: r.get(k) for k in ("symbol", "close", "last", "close_pct", "setups", "real_power", "value",
                                     "real_net_value", "queue", "band_min", "band_max")}
             for r in (w.get("symbols") or [])[:40]]
    return {
        "mode": cfg.get("mode", "paper"), "market": st, "status": STATUS,
        "account": s | {"start_cash_rial": p["start_cash_rial"], "cash_rial": p["cash_rial"],
                        "free_cash_rial": I.account_cash_rial(cfg), "created": p["created"],
                        "today_pnl_rial": (s["equity_rial"] - base), "open_risk_rial": round(open_risk)},
        "positions": positions,
        "orders": sorted(p["orders"], key=lambda o: o["id"], reverse=True)[:40],
        "trades": list(reversed(p["trades"]))[:100],
        "equity": p["equity"][-600:],
        "events": list(reversed(I.read_json("paper_events.json", []) or []))[:40],
        "watchlist": watch, "watchlist_at": w.get("jalali"),
        "rules": {k: cfg.get(k) for k in ("max_loss_per_trade_toman", "max_daily_loss_toman", "max_position_pct",
                                           "cash_buffer_pct", "min_reward_risk", "max_trades_per_day",
                                           "fee_buy", "fee_sell", "entry_window", "paper_auto_exits")},
        "currency": cfg.get("display_currency", "toman"),
    }


def quote_info(sym: str):
    cfg = I.config()
    info = I.resolve(sym)
    q = I.quote(info["insCode"])
    fb, fs = I.fees(cfg)
    bars = I.daily(info["insCode"], days=60)
    at = I.atr(bars, 14)
    last = q["last"] or q["yesterday"]
    sug = {}
    if at and last:
        stop = I.round_tick(last - 1.5 * at, cfg)
        cost = last * (1 + fb)
        risk = cost - stop * (1 - fs)
        target = I.round_tick((cost + 2 * risk) / (1 - fs), cfg, down=False)
        equity, free = I.account_equity_rial(cfg), I.account_cash_rial(cfg)
        lims = {"max_loss": int((cfg.get("max_loss_per_trade_toman") or 0) * 10 // risk) if cfg.get("max_loss_per_trade_toman") else 10**12,
                "position": int(equity * cfg["max_position_pct"] / 100 // cost),
                "cash": max(0, int((free - equity * cfg["cash_buffer_pct"] / 100) // cost))}
        sug = {"price": last, "stop": stop, "target": target, "atr": round(at, 1), "qty": max(0, min(lims.values())),
               "decided_by": min(lims, key=lims.get)}
    pos = next((x for x in P.load()["positions"] if x["insCode"] == info["insCode"]), None)
    return {"symbol": q["symbol"], "name": q["name"], "insCode": info["insCode"], "last": q["last"], "close": q["close"],
            "yesterday": q["yesterday"], "chg_pct": q["chg_pct"], "band_min": q["band_min"], "band_max": q["band_max"],
            "queue": q["queue"], "state": q["state"], "state_code": q["state_code"], "high": q["high"], "low": q["low"],
            "value": q["value"], "book": q["book"][:3], "suggest": sug, "held": pos["qty"] if pos else 0,
            "date": q["date"], "fee_buy": fb, "fee_sell": fs}


def place_order(body):
    cfg = I.config()
    info = I.resolve(body["symbol"])
    o = {"symbol": info["symbol"], "insCode": info["insCode"], "side": body.get("side", "buy"),
         "qty": int(float(body.get("qty") or 0)), "price": float(body.get("price") or 0)}
    if o["side"] == "buy":
        o["stop"] = float(body["stop"]) if body.get("stop") else None
        o["target"] = float(body["target"]) if body.get("target") else None
    o["id"] = I.order_hash(o)
    with LOCK:
        r = R.check(o, cfg)
        log = I.read_json("risk_log.json", {}) or {}
        log.setdefault(I.today_key(), []).append(r | {"order_id": o["id"], "symbol": o["symbol"], "side": o["side"],
                                                     "qty": o["qty"], "price": o["price"], "checked_at": I.market_status()["now"],
                                                     "source": "dashboard"})
        I.write_json("risk_log.json", log)
        if r["verdict"] != "PASS":
            return {"ok": False, "risk": r}
        rec = P.place(o, source="dashboard")
    ev = safe_update()
    return {"ok": True, "risk": r, "order": rec, "events": ev}


def run_scan():
    STATUS["scan_running"] = True
    STATUS["scan_msg"] = "در حال اسکن…"
    try:
        out = subprocess.run([sys.executable, "-X", "utf8", str(SKILLS / "iran-scanner" / "scanner.py"), "scan",
                              "--top", "80", "--limit", "5"], capture_output=True, text=True, encoding="utf-8",
                             timeout=600)
        STATUS["scan_msg"] = (out.stdout.strip().splitlines() or ["تمام شد"])[0] if out.returncode == 0 else (out.stdout + out.stderr)[-300:]
    except Exception as e:
        STATUS["scan_msg"] = f"خطا: {e}"
    finally:
        STATUS["scan_running"] = False


# ---------------------------------------------------------------- http
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        try:
            if u.path in ("/", "/index.html"):
                html = (HERE / "dashboard.html").read_text(encoding="utf-8").replace("__TOKEN__", TOKEN)
                return self.send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            if u.path == "/api/state":
                return self.send(200, state())
            if u.path == "/api/quote":
                s = (parse_qs(u.query).get("s") or [""])[0]
                return self.send(200, quote_info(s))
            self.send(404, {"error": "not found"})
        except I.IranError as e:
            self.send(400, {"error": str(e)})
        except Exception as e:
            self.send(500, {"error": f"{type(e).__name__}: {e}"})

    def do_POST(self):
        if self.headers.get("X-Token") != TOKEN:
            return self.send(403, {"error": "forbidden"})
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            body = {}
        try:
            path = urlparse(self.path).path
            if path == "/api/update":
                return self.send(200, {"events": safe_update()})
            if path == "/api/order":
                return self.send(200, place_order(body))
            if path == "/api/cancel":
                with LOCK:
                    o = P.cancel(int(body["id"]))
                return self.send(200, {"ok": True, "order": o})
            if path == "/api/reset":
                cash = float(body.get("cash") or I.config()["paper_start_cash_toman"])
                with LOCK:
                    P.save(P.new_account(cash))
                    I.write_json("paper_events.json", [])
                safe_update()
                return self.send(200, {"ok": True})
            if path == "/api/scan":
                if not STATUS["scan_running"]:
                    threading.Thread(target=run_scan, daemon=True).start()
                return self.send(200, {"ok": True})
            self.send(404, {"error": "not found"})
        except I.IranError as e:
            self.send(400, {"error": str(e)})
        except Exception as e:
            self.send(500, {"error": f"{type(e).__name__}: {e}"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    threading.Thread(target=updater, daemon=True).start()
    url = f"http://127.0.0.1:{a.port}/"
    print(f"داشبورد آزمایشی: {url}   (Ctrl+C برای توقف)", flush=True)
    if not a.no_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
