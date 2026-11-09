---
name: iran-scanner
description: >-
  Chart Scanner for the Iranian stock market (بورس تهران و فرابورس). Scans every listed share in one
  request from TSETMC's market watch (دیده‌بان بازار) for Iran-specific setups: buy queues (صف خرید),
  sell queues (صف فروش), real-money inflow (ورود پول حقیقی) and buyer power (قدرت خریدار حقیقی),
  then pulls daily history for the most-traded names for volume spikes, 20-day breakouts, reclaiming
  the 20-day average, oversold RSI and bounces. Prices are back-adjusted for capital raises and
  dividends. Writes trader/watchlist.json for /iran-news and /iran-entry. Use when the user says
  "scan the market", "find me setups", "اسکن کن", "چه سهمی خوبه", "صف خریدها", "ورود پول حقیقی",
  "پول هوشمند", "سهم‌های پرحجم", "build my watchlist", "what should I look at today", or at the start
  of a trading day.
argument-hint: "[scan | show | add SYMBOL]"
---

# iran-scanner

Script: `python ~/.claude/skills/iran-scanner/scanner.py <command>`

| Command | What it does |
|---|---|
| `scan` | Full scan: live setups for every share, plus daily setups for the top 150 by value traded (~15–60 s) |
| `scan --no-daily` | Live setups only, in one request (~5 s) |
| `scan --setups buy_queue,smart_money` | Only these setups |
| `scan --min-value 5000000000` | Minimum value traded today, in **Toman** (default 2 billion Toman) |
| `show` | Print the last watchlist |
| `add فولاد شستا` / `remove ...` | Manual watchlist (always checked by /iran-news and /iran-entry) |

## Setups

Live setups come from a single market-watch request and work during and after the session:

- `buy_queue`: last price at the upper limit, sell side empty. Strong demand, but a new buy order
  joins the back of the queue.
- `sell_queue`: at the lower limit, buy side empty. This is a **warning**, not a buy idea.
- `smart_money`: real (individual) net inflow of at least 1 billion Toman, with buyer power of at
  least 1.5.
- `real_power`: buyer power (per-capita real buy ÷ per-capita real sell) of at least 2.

Daily setups use history for the most-traded symbols, cached per day:

- `volume_spike`: today's volume at least 2× the 20-day average.
- `breakout20`: close above the highest close of the previous 20 sessions.
- `reclaim_ma20`: back above the 20-day average after closing below it.
- `oversold`: RSI(14) ≤ 30.
- `bounce`: RSI was ≤ 30 in the last 3 sessions and today closed up.

## How to report

Show the table the script prints (top 15–30). Then add two or three plain sentences: how broad the
market is (many buy queues means a hot day, many sell queues a weak one) and which names have
several setups at once. Point out that `buy_queue` names are hard to buy and `sell_queue` names
are warnings.

During the session, values are live. After 12:30 they are the day's final numbers. Before 09:00 the
scan shows the previous session.

Next steps: `/iran-news` (anything official on these names?), then `/iran-entry` (timing).

Notes: shares only (TSE main and secondary boards and Fara Bourse). The base market (بازار پایه) and
rights (حق تقدم) are excluded unless `allow_base_market` / `allow_rights` are set in
`E:/projects/iran-trader/trader/config.json`. Data comes from TSETMC's public API, with no login.
This is a scan, not advice: say so once when the user treats a setup as a buy signal.
