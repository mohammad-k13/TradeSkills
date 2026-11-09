---
name: iran-alerts
description: >-
  Price Alerts for Iranian stocks. Rings once when a price, a stop, a target, a percent move, a
  queue event or a time hits: above / below / stop / target levels, % move from yesterday, a buy
  queue forming (صف خرید), a buy queue breaking (شکست صف), a sell queue forming (صف فروش), any Tehran
  time of day, and the opening bell. It turns the plan or every open position into stop and target
  alerts in one go, knows the TSE session (Sat–Wed 09:00–12:30 Tehran) and Iran's fixed holidays,
  gives quick live quotes with the daily limit and queue status, and writes trader/prices.json. An
  alert is information, never an order. Use when the user says "alert me when", "خبرم کن وقتی",
  "هشدار بذار", "watch my stop", "حد ضررم رو بپا", "tell me if the queue breaks", "صف خرید شکست",
  "is the market open", "بازار بازه؟", "قیمت فولاد", "get me a price", or after a buy fills.
argument-hint: "[add SYMBOL KIND VALUE | from-positions | check | watch | price SYMBOL]"
---

# iran-alerts

Script: `python ~/.claude/skills/iran-alerts/alerts.py <command>`

| Command | What it does |
|---|---|
| `add فولاد above 4800` / `below` / `stop` / `target` | Price levels in Rial |
| `add فولاد pct +3` / `pct -2` | Move from yesterday's close |
| `add فولاد buy_queue_break` | Arms when a buy queue is seen and rings when it breaks |
| `add فولاد buy_queue` / `sell_queue` | Rings when the queue forms |
| `add - time 12:20 --note "خروج؟"` / `add - open` | Time of day / the opening bell |
| `from-plan` / `from-positions` | Stop and target alerts from `plan.json` / every open position |
| `list` · `remove ID` · `clear` | Manage alerts |
| `check` | One pass: prints what rang (each alert rings once) |
| `watch --every 60 --until 12:30` | Loop until the time and print rings as they happen |
| `price فولاد شستا` | Quick quotes: last, %, close, band, state, queue |
| `market` | Is the market open, and when is the next session |

## Watching during the session

Run `watch` with `run_in_background: true` (it ends by itself at 12:30), or use `/loop 2m` with
`alerts.py check`. When a **stop** rings, tell the user right away and offer
`broker.py close SYMBOL` → `/iran-risk` → ticket. Never sell on your own.

Lunar (religious) holidays move every year and aren't built in. If the user mentions one, or a
session unexpectedly has no trades, add it to `trader/config.json` → `holidays_jalali`
(`"1405-09-05"`). `check` already stays silent on days with no trades.
