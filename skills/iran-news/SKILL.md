---
name: iran-news
description: >-
  News Monitor for Iranian stocks. For every symbol the user watches it pulls official Codal
  announcements (کدال: financial statements, monthly activity reports, AGMs, capital raises,
  dividends, material disclosures), TSETMC watchdog messages (پیام ناظر: halts, reopenings,
  cancelled trades) and headlines from Sena, BourseNews, Nabz-e Bourse, Shahr-e Bourse,
  EghtesadNews and Bourse24. It shows only what is new since the last check, newest first, in
  Tehran time, tags each item (earnings, capital raise, AGM, halt, macro...), separates official
  items from site news, and adds the stock's move and queue status. Use when the user says "any news
  on فولاد", "خبر جدید", "چرا این سهم صف شده", "why is this moving", "morning briefing", "کدال",
  "اطلاعیه", "صورت مالی جدید", "مجمع", "افزایش سرمایه", "check my watchlist news", or after
  /iran-scanner.
argument-hint: "[SYMBOL ...] [--market]"
---

# iran-news

Script: `python ~/.claude/skills/iran-news/news.py <command>`

| Command | What it does |
|---|---|
| `check فولاد شستا` | News for these symbols (last 48 h, only items not shown before) |
| `check` | Manual watchlist + open positions + top 15 from the last scan |
| `check --market` | Also print general market headlines that name no watched symbol |
| `check --hours 168 --all-seen` | Look back a week, including items already shown |
| `codal فولاد --pages 2` | Raw list of the latest Codal letters for one symbol |
| `sources` | The configured news sites |
| `reset` | Forget what was already shown |

## Sources

- ★ **Official:** Codal (search.codal.ir) and TSETMC watchdog messages. These are the ground truth.
- · **News sites** (in `trader/config.json` → `news_sources`): سنا (sena.ir), بورس‌نیوز, نبض بورس,
  شهر بورس, اقتصادنیوز (RSS) and بورس۲۴ (HTML). Add or remove entries there. Each needs `name`,
  `url` and `type` (`rss` or `html` with a `link_pattern`).

A headline counts as being about a symbol when the symbol is quoted («فولاد», (فولاد), #فولاد,
نماد فولاد) or the company's name appears. Bare words don't count, because many symbols are
ordinary words (فولاد = steel, جم, فارس, خودرو).

## How to report

Lead with official items (★), grouped by symbol, with the price move and queue status the script
adds. Summarize what matters in one line each. For example: «صورت مالی ۶ ماهه حسابرسی‌شده منتشر
شد», «مجمع افزایش سرمایه ۳۰ آبان», «نماد متوقف شد». Link the Codal letter. Then list site
headlines briefly.

Always keep this rule: news sites and analysis are **opinion**. Before any buy decision, the user
should confirm the fact in Codal. Treat "best signal site" content as advertising. If a site fails,
the script lists it at the end. Say so and carry on.

A halt (توقف) or a watchdog warning on a held position matters most: put it first.
