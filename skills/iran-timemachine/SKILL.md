---
name: iran-timemachine
description: >-
  Time Machine for Iranian stocks. Replays the plan from /iran-exit (entry, stop, target, hold) 10,000
  times on this stock's own last 250 sessions of back-adjusted daily bars, and re-runs the same
  stop and target distances on every past session (or only past 20-day breakouts). It models what
  matters in Tehran: the daily price limit, gaps through the stop, and sessions locked in a sell
  queue where nobody can sell. Fees are included. Prints the odds of target first, stop first or time
  out, the average R and the spread of outcomes, the break-even hit rate, and one honest verdict
  (positive / coin flip / negative). Use when the user says "run the time machine", "what are the
  odds", "شانس موفقیت", "بک‌تست", "backtest this", "simulate this trade", "monte carlo", "is this a
  coin flip", or after /iran-exit, before /iran-budget.
argument-hint: "[--setup breakout20] [--hold N]"
---

# iran-timemachine

Script: `python ~/.claude/skills/iran-timemachine/tm.py run [--sims 10000] [--days 250] [--hold N] [--setup breakout20]`

It reads `trader/plan.json`. Run `/iran-exit` first. It takes about a second.

## What it does

1. **Monte Carlo.** Each simulated future is up to `--hold` sessions, each drawn at random from
   the stock's real sessions (open, high, low and close relative to the previous close, clipped to
   the daily limit).
2. **History.** The same stop and target distances are entered at the close of every past session
   (`--setup breakout20`: only sessions that closed above the prior 20-day high) and walked through
   what really happened.

Rules per session: open at or below the stop means out at the open (gap). Low at or below the stop
means stopped. High at or above the target means target. Both on one day counts as the stop
(conservative). A session locked at the lower limit means no exit; the stop waits for the next
session. If the trade is still open after `--hold` sessions, it exits at the close.

## How to report

Give the two result lines and the verdict in plain words. For example: «در ۱۰٬۰۰۰ مسیر، ۱۴٪ به هدف
رسید، ۳۲٪ به حد ضرر، بقیه با پایان مهلت؛ میانگین ۰٫۲۴R». Then add the break-even rate. Be honest:
a "coin flip" or "negative" verdict means say so plainly and suggest changing the plan or skipping
the trade. A small history sample (under 30) is weak evidence. The script notes it; repeat that.

Limits to mention when relevant: daily bars only (the rest of the entry day isn't simulated), past
behaviour isn't the future, and news-driven gaps such as AGMs or halts can be larger than history
shows.

Next: `/iran-budget`.
