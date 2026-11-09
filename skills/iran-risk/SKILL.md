---
name: iran-risk
description: >-
  Risk Manager for Iranian stocks. Checks the pending order against every limit before it can reach
  the broker and prints PASS or BLOCK with reasons. For a buy it checks: a stop is required; the loss
  at the stop (measured from the HIGHER of the order price and a fresh TSETMC price, fees included)
  must fit the max loss per trade; reward:risk must meet the minimum; the day's total risk must fit
  the daily loss limit; trades and orders per day; position cap and cash buffer; price inside
  today's daily limit; market open and inside the entry window (Sat–Wed 09:00–12:00 Tehran); the
  symbol must be «مجاز» (not halted); base market, rights and under-supervision symbols are blocked
  unless allowed; duplicates. It warns on buy queues (likely no fill), sell queues, real money
  leaving, a negative Time Machine verdict and ideas that came from Telegram signals. Getting out is
  never blocked by daily limits. Records every verdict. Use when the user says "check my order",
  "risk check", "بررسی ریسک", "is this safe", "can I take this trade", "how much have I risked
  today", or before /iran-broker, always.
argument-hint: "[check | today | log]"
---

# iran-risk

Script: `python ~/.claude/skills/iran-risk/risk.py <command>`

| Command | What it does |
|---|---|
| `check` | Check the pending order in `trader/orders.json` and print PASS or BLOCK |
| `today` | Risk used today, entries, orders |
| `log --days 3` | Past verdicts |

Run `check` before every `/iran-broker` step, including sells. The broker refuses an order without
a PASS from the last 10 minutes, or one that changed after the check.

## How to report

Lead with the verdict. For a BLOCK, give each ✖ reason in plain words and the fix. For example:
«بازار بسته است → فردا ساعت ۹», «ضرر در حد ضرر بیشتر از سقف شماست → تعداد کمتر یا حد ضرر
نزدیک‌تر (budget.py size)». For a PASS, mention any ⚠ warnings before moving on, especially a buy
queue (the order may never fill) and Telegram-sourced ideas.

Never suggest editing config limits just to make a blocked order pass, unless the user explicitly
asks to change their rules. If they do, change them with `budget.py rules` and say what changed.
Limits are in `E:/projects/iran-trader/trader/config.json`.
