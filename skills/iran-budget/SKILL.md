---
name: iran-budget
description: >-
  Budget Manager for Iranian stocks. Sizes every position in whole shares to the user's cash and max
  loss per trade, in Toman, with broker fees counted. It reads the plan from /iran-exit (entry, stop,
  target) and takes the smallest of four limits (max loss per trade, position cap as % of cash, max
  order value, cash after the buffer), says which one decided, and writes ONE limit order to
  trader/orders.json. It keeps the order price inside today's daily limit. A stop too far for the max
  loss is a refusal, not a smaller order. Nothing is placed. Also stores the user's rules: cash, max
  loss, daily loss limit, position %, buffer, minimum R:R and fees. Use when the user says "how many
  shares", "چند سهم بخرم", "چقدر بخرم", "size this trade", "I have 50 million toman", "I only want to
  risk 1 million a trade", "قوانین من", "set my rules", "کارمزد", or after /iran-exit.
argument-hint: "[size | rules --cash T --max-loss T]"
---

# iran-budget

Script: `python ~/.claude/skills/iran-budget/budget.py <command>`. **All money amounts are in Toman.
Share prices are in Rial.**

| Command | What it does |
|---|---|
| `rules` | Show the user's rules |
| `rules --cash 50000000 --max-loss 1000000 --daily-loss 3000000` | Save rules (Toman) |
| `rules --position-pct 25 --buffer 10 --min-rr 1.5 --max-order 20000000` | More rules |
| `rules --fee-buy 0.003712 --fee-sell 0.0088` | Fees as fractions; check the broker's fee sheet (کارمزد) |
| `size` | Size the plan in `plan.json` using the saved rules |
| `size --cash ... --max-loss ... --price 3910` | One-off values; `--price` is the limit price in Rial |
| `show` | The pending order |

If the user hasn't set cash and max loss, ask for both in one question («نقدینگی و حداکثر ضرری که
در هر معامله می‌پذیرید، به تومان؟»), save them with `rules`, then `size`.

Report the order line, the cost with fees, the loss at the stop, the gain at the target, and which
limit decided the size. Make clear nothing was sent.

Next: `/iran-risk` (always).
