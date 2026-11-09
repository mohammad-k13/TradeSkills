---
name: iran-paper
description: >-
  Paper trading (حساب آزمایشی) for the Tehran Stock Exchange: a demo account with fake money, 3.5
  million Toman by default, that runs on REAL TSETMC prices, plus a local web dashboard to watch and
  test it. Orders fill only when the real market trades at the user's price; a buy at the upper limit
  waits behind the real buy queue (صف خرید); fees are charged; orders last one session; off-hours
  orders wait for the next session; stops and targets are executed automatically on real trades,
  gaps included. The dashboard shows account value, total and today's return, free cash, open risk,
  an equity curve, positions with live P/L, orders, the scanner watchlist, an order ticket with
  suggested stop, target and size, the track record (win rate, average R, profit factor, drawdown)
  and an event feed. Every order still passes /iran-risk. In paper mode (the default) /iran-broker
  sends approved orders here instead of EasyTrader. Use when the user says "paper trading",
  "demo account", "حساب آزمایشی", "حساب دمو", "تمرین", "test without real money", "open the
  dashboard", "داشبورد", "how is my demo doing", "reset my demo account", or wants to practise.
argument-hint: "[dashboard | status | buy | sell | reset]"
---

# iran-paper

Scripts: `python ~/.claude/skills/iran-paper/paper.py <command>` and
`python ~/.claude/skills/iran-paper/dashboard.py`. The account lives in `E:/projects/iran-trader/trader/paper.json`.

## Dashboard

Start it with `run_in_background: true`. It prints its URL and opens the browser:
`python ~/.claude/skills/iran-paper/dashboard.py`. The URL is http://127.0.0.1:8765, reachable only
from this PC. The user can also double-click `E:\projects\iran-trader\dashboard.cmd`.

- During the session it checks the account against real trades every 30 seconds. The page refreshes
  every 15 seconds.
- The order ticket shows the live quote, the daily limit and queue state, and suggests a stop
  (1.5×ATR), a target (2R after fees) and a quantity (from the user's rules). It previews cost,
  loss at the stop, gain at the target and R:R, then runs the same risk check as `/iran-risk`. A
  BLOCK is shown with its reasons and nothing is placed.
- The «اسکن بازار» button runs `/iran-scanner` and fills the watchlist. «بررسی» on any row loads that
  symbol into the ticket.

## CLI

| Command | What it does |
|---|---|
| `status` | Update against real trades, then print value, positions, orders and stats |
| `update` | Fill or expire orders and run stops and targets |
| `buy فولاد 200 4600 --stop 4400 --target 5000` | Paper buy (risk-checked; `--no-risk` skips the check, for testing only) |
| `sell فولاد [QTY] [PRICE]` | Paper sell (default: everything, at the best bid) |
| `cancel ID` · `history` | Cancel an open order · closed trades |
| `reset --cash 3500000` | Start a new account (Toman). **Ask the user first**: it erases the paper history |

## How fills work (tell the user when they ask why something did or didn't fill)

- A buy limit fills at the first real trade *after* the order at or below its price, at that
  trade's price. A sell fills at or above its price.
- In a buy queue at the upper limit, the order waits behind every share that was queued ahead of it
  when it was placed. It fills only after that much volume has traded at that price, or when the
  price trades through. A sell in a sell queue works the same way.
- No partial fills. Orders expire at the end of their session.
- Auto exits: the first real trade at or below the stop sells at that trade's price (so it can be
  worse than the stop). A target sells at the target. `paper_auto_exits` in config turns this off.
- What it can't model: your own order moving the price, and the fill-order details of the opening
  auction.

## Paper vs live

`trader/config.json` → `"mode": "paper"` (the default) or `"live"`. In paper mode `/iran-broker`
records the yes and then puts the order into this account instead of opening EasyTrader. Switch to
`live` only when the user explicitly asks to trade real money, and suggest at least 2–3 weeks of
paper results first. Show them `status` (win rate, average R, drawdown) before they decide.
