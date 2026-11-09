---
name: iran-entry
description: >-
  Entry Timer for Iranian stocks. Builds 1–15 minute bars from TSETMC's trade-by-trade data, forms the
  opening range (first 15 minutes after 09:00 Tehran by default) and calls the entry on the first
  completed bar that CLOSES above the range high or above a level the user gives (such as a 20-day
  high from /iran-scanner), with an optional volume check. Knows Iran's daily price limit: it says
  when a breakout is impossible today because the level is above the upper limit, or the stock is
  locked in a buy queue (صف خرید). States: waiting with distance, triggered with time and price,
  expired, not open yet, halted. Replays past sessions with --date. Writes trader/entry.json for
  /iran-exit. Long side only; never places an order. Use when the user says "tell me when to get in",
  "watch فولاد", "کی وارد بشم", "شکست مقاومت", "has it broken out", "opening range", "time my entry",
  or after /iran-scanner and /iran-news.
argument-hint: "SYMBOL [--level PRICE]"
---

# iran-entry

Script: `python ~/.claude/skills/iran-entry/entry.py <command>`

| Command | What it does |
|---|---|
| `check شستا` | Opening-range breakout check, using 5-minute bars and a 15-minute range |
| `check شستا --level 3500` | Trigger on a close above your level |
| `check شستا --bar 1 --or 30 --vol 1.5` | 1-minute bars, 30-minute range, volume at least 1.5× the average bar |
| `check شستا --date 20261108` | Replay a past session (the band is approximated at ±3%) |
| `watchlist [--use-high20]` | Check the top 10 watchlist names. `--use-high20` uses each breakout20 name's 20-day high as its level |

## States

| State | Meaning | What to tell the user |
|---|---|---|
| `not_open` | Before 09:00, a holiday, or no trade today | When the next session starts (`alerts.py market`) |
| `building_range` | The opening range isn't complete yet | When it will be complete |
| `waiting` | Still under the level | The distance in % |
| `triggered` | A completed bar closed above the level | Time and price; next is /iran-exit |
| `expired` | Past the entry window (12:00) or the session ended without a trigger | No trade today |
| `level_above_band` / `queue_locked` | The level is at or above today's upper limit; the price can't get there today. In a buy queue, a buy order only joins the queue | Explain the daily limit |
| `halted` | Symbol not «مجاز» | Run /iran-news to find out why |

To watch live, rerun `check` every few minutes during 09:15–12:00, or use `/loop 5m` with the
check command. Each check costs a few TSETMC requests.

Then: `/iran-exit` (stop and target), `/iran-timemachine` (odds), `/iran-budget` (size).
