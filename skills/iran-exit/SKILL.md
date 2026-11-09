---
name: iran-exit
description: >-
  Exit Planner for Iranian stocks. Sets the stop and the target before the buy: stop at 1.5× the
  14-day ATR by default (or the opening-range midpoint or low, a percent, the lowest low of N
  sessions, or a price), target at 2R AFTER fees (~0.37% buy + ~0.88% sell) or a price or percent.
  Refuses a stop at or above the entry, a target at or below it, and a stop so tight that fees eat
  half the risk. Uses Iran's daily price limit to say how many sessions the target needs at least,
  warns when the stop is below today's lower limit, and warns that a stop may not fill in a sell
  queue (صف فروش). Writes trader/plan.json for /iran-timemachine, /iran-budget and /iran-alerts. Long
  only. Use when the user says "where's my stop", "حد ضرر", "حد سود", "تارگت", "set my stop and
  target", "risk reward", "R", "کی خارج بشم", or right after /iran-entry triggers.
argument-hint: "[SYMBOL] [--entry P] [--stop MODE] [--target MODE]"
---

# iran-exit

Script: `python ~/.claude/skills/iran-exit/exit.py plan [SYMBOL] [options]` · `exit.py show`

| Option | Values (prices in **Rial**, as TSETMC quotes them) |
|---|---|
| `--entry` | Default: the triggered entry in `entry.json`, else the live last price |
| `--stop` | `atr:1.5` (default) · `or-mid` · `or-low` · `pct:4` · `low:5` · `price:4410` |
| `--target` | `r:2` (default, after fees) · `pct:8` · `price:5200` |
| `--hold` | Maximum sessions to hold (default 10). After that the plan says exit at the close |

## Why the defaults differ from a US day-trade plan

- **Daily limit (usually ±3%).** A 2R target is often 3–6 sessions away. The plan prints the
  minimum number of sessions, so the default is a swing plan (`--hold 10`), not a same-day exit.
- **Round-trip fees are about 1.25%.** An opening-range-midpoint stop (`or-mid`) is often only
  1–2% away and gets refused as too tight. The ATR stop leaves room.
- **Stops aren't guaranteed.** In a sell queue nobody can sell. The plan always says so. After
  buying, the user sets alerts (`/iran-alerts from-positions`) or a conditional order at the broker.

## How to report

Paste the block the script prints (entry / stop / target / R:R / sessions / warnings). Explain any
warning in one sentence. If it refused, say why and suggest the fix it gives.

Next: `/iran-timemachine` to see the odds, then `/iran-budget` to size it.
