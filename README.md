# iran-trader

Claude Code skills for trading the Tehran Stock Exchange and Fara Bourse (بورس تهران و فرابورس).
Python stdlib only, public data only, and nothing is ever sent to a broker without the user's explicit yes.

| Skill | What it does |
|---|---|
| `/iran-scanner` | Scans every share for buy and sell queues, real-money inflow, buyer power, volume spikes, 20-day breakouts, MA20 reclaims, oversold readings and bounces → `trader/watchlist.json` |
| `/iran-news` | Codal announcements, TSETMC watchdog messages, and headlines from Sena, BourseNews, Nabz-e Bourse, Shahr-e Bourse, EghtesadNews and Bourse24. Shows only what's new |
| `/iran-entry` | Opening-range or level breakout from trade-by-trade bars. Knows the daily limit and queue locks → `trader/entry.json` |
| `/iran-exit` | Stop (ATR / opening range / % / low / price) and target (R after fees). Counts sessions needed under the daily limit → `trader/plan.json` |
| `/iran-timemachine` | 10,000 Monte Carlo futures plus a historical replay, with fees, gaps and locked sell-queue days |
| `/iran-budget` | Whole-share sizing in Toman under four limits → one limit order in `trader/orders.json` |
| `/iran-risk` | PASS/BLOCK on every limit, market hours, band, halt state and daily risk |
| `/iran-broker` | Ticket, then the user's yes, then fills the EasyTrader (d.easytrader.ir) form in the user's Chrome, then a second yes. Also records fills and positions |
| `/iran-alerts` | Price, stop, target, %, queue-form and queue-break, time and opening-bell alerts, plus quick quotes |
| `/iran-signals` | Reads public Telegram signal channels, parses the signals and grades each channel against real prices |
| `/iran-paper` | Demo account (default 3.5M Toman) on real prices: fills on real trades, queues, fees, auto stop/target |

**Mode:** `trader/config.json` → `"mode": "paper"` (the default) sends approved orders to the demo
account. `"live"` uses EasyTrader through Chrome.

Typical day: `scanner → news → entry → exit → timemachine → budget → risk → broker → alerts`.

## Data sources

- **TSETMC** `cdn.tsetmc.com/api`: market watch, quotes, order book, real/legal flow, daily band,
  daily history (back-adjusted for capital raises and dividends), trades, watchdog messages.
- **Codal** `search.codal.ir`: company announcements.
- News sites: RSS/HTML, configured in `trader/config.json` → `news_sources`.
- Telegram: `t.me/s/<channel>` public previews.

## Layout

```
skills/iran-common/iran.py   shared library (HTTP, TSETMC/Codal, Jalali calendar, market hours, config)
skills/iran-*/SKILL.md       instructions Claude reads
skills/iran-*/*.py           the scripts the skills run
trader/                      your data: config, watchlist, plans, orders, journal, cache (git-ignored)
```

Each `skills/iran-*` folder is linked into `~/.claude/skills/` with a directory junction:

```powershell
Get-ChildItem E:\projects\iran-trader\skills -Directory | % { New-Item -ItemType Junction -Path "$env:USERPROFILE\.claude\skills\$($_.Name)" -Target $_.FullName }
```

## Config (`trader/config.json`)

The file is created on the first `budget.py rules` call. Money is in **Toman** and share prices are
in **Rial**. Keys and their defaults are in `DEFAULT_CONFIG` in `skills/iran-common/iran.py`: fees,
session hours, entry window, holidays (add the lunar ones each year to `holidays_jalali`), scanner
thresholds, news sources, signal channels and the broker URL.

Testing: set `IRAN_TRADER_NOW="2026-11-09 10:15"` to fake Tehran time. The broker refuses to work
while it is set.
