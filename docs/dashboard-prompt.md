# Prompt: Persian trading dashboard (Next.js + database)

Copy everything below the line into Claude Code (or another AI coding tool), in a new empty folder.

---

Build a production-quality, beautiful **Persian (RTL) trading dashboard** for one person who trades
the Tehran Stock Exchange (بورس تهران / فرابورس). It stores every order they create and everything
they do, then shows their activity and an honest performance report: how much they made, how much
they lost, and overall how good or bad they were.

## Stack

- **Next.js 15** (App Router, Server Components, Server Actions) + **TypeScript** (strict).
- **Tailwind CSS v4** + **shadcn/ui** (Radix), configured for RTL (`<html lang="fa" dir="rtl">`,
  logical properties `ms-/me-/ps-/pe-`, mirrored icons where direction matters).
- **Font: Vazirmatn**, self-hosted with `next/font/local` (variable font, weights 300–800). Use
  Persian digits in the UI (`Intl.NumberFormat('fa-IR')`) but keep inputs tolerant of both Persian
  and Latin digits.
- **Jalali (Shamsi) dates everywhere** (`date-fns-jalali` or `dayjs` + `jalaliday`). Store UTC in
  the database; display in Asia/Tehran (UTC+03:30).
- **Database: PostgreSQL** (Neon via the Vercel Marketplace) with **Drizzle ORM** and migrations
  (`drizzle-kit`). Seed script with realistic fake data so every page looks alive on first run.
- **Charts: Recharts.** Tables: TanStack Table. Forms: react-hook-form + zod.
- **Auth:** single user. Password login with Auth.js (Credentials) or a signed-cookie middleware.
  The password hash lives in an env var. Every page and API route is protected.
- **Deploy on Vercel**, with the repo on GitHub. Put all secrets in env vars (`DATABASE_URL`,
  `AUTH_SECRET`, `ADMIN_PASSWORD_HASH`, `INGEST_TOKEN`). Ship an `.env.example`.

## Money and market rules (must be correct)

- Share prices are in **Rial**. All money totals are shown in **Toman** (Rial ÷ 10), with compact
  Persian units (هزار / میلیون / میلیارد تومان).
- Fees (editable in Settings): buy 0.3712%, sell 0.88% (including 0.5% tax). Every P/L figure is
  **net of fees**.
- Market: Saturday–Wednesday, 09:00–12:30 Tehran. Daily price limit (دامنه نوسان) is usually ±3%.
  Long only (no short selling).
- Two modes on every record: `paper` (demo money) and `live` (real money). A global switch in the
  header filters the whole app: آزمایشی / واقعی / همه. Never mix them silently.

## Data model (Drizzle)

- `orders`: id, created_at, mode, symbol, company_name, side (buy|sell), qty, price_rial,
  stop_rial, target_rial, status (draft|blocked|approved|sent|filled|partially_filled|cancelled|expired),
  source (scanner|signal|news|manual), setup_tags text[], risk_verdict (PASS|BLOCK|null),
  risk_reasons jsonb, planned_risk_toman, planned_reward_toman, rr_planned, note, external_id (unique,
  for idempotent sync).
- `fills`: id, order_id → orders, filled_at, qty, price_rial, fee_toman.
- `trades` (one round trip, buy → sell): id, mode, symbol, opened_at, closed_at, qty, entry_avg_rial,
  exit_avg_rial, fees_toman, pnl_toman, pnl_pct, r_multiple, exit_reason
  (stop|target|manual|time|other), planned_stop_rial, planned_target_rial, followed_plan boolean,
  holding_sessions, setup_tags text[], source, external_id (unique).
- `equity_snapshots`: ts, mode, equity_toman, cash_toman (unique on ts+mode).
- `activities`: id, ts, mode, type (scan|news_check|plan|risk_check|order_created|approval|fill|alert|
  exit|note|rule_change), symbol nullable, title (Persian, one line), payload jsonb.
- `journal`: trade_id → trades, emotion (calm|fomo|fear|greedy|revenge|bored), mistakes text[]
  (moved_stop|no_stop|oversized|chased|early_exit|late_exit|ignored_news|broke_rules), lesson text,
  rating 1–5.
- `settings`: single row: start_capital_toman, max_loss_per_trade_toman, max_daily_loss_toman,
  max_position_pct, fees, display currency.

## Pages (all Persian, RTL, responsive down to 360px)

1. **داشبورد (Overview)**
   - KPI cards: account value, total return %, today's P/L, this month's P/L, win rate, open risk.
   - Equity curve with a dashed starting-capital line and drawdown shading.
   - Open positions with unrealized P/L, plus the last 5 activities and the last 5 closed trades.
2. **ثبت سفارش (New order)**
   - Form: symbol, side, qty, price, stop, target, source, setup tags, note.
   - Live preview: cost with fees, loss at stop, gain at target, R:R after fees, and % of capital
     at risk.
   - Validation against the Settings limits: show PASS or BLOCK with reasons, in the same spirit as
     a risk manager. A BLOCKed order can still be saved, as blocked, for the record.
   - Saving creates the order and an `activities` row. A "mark as filled" / "close trade" flow
     creates `fills` and `trades`.
3. **سفارش‌ها (Orders)**
   - Filterable table: status, mode, symbol, date range (Jalali picker), source.
   - Row drawer with full details, risk reasons, fills, and actions (cancel, fill, close, edit note).
4. **فعالیت‌ها (Activity)**
   - Vertical timeline grouped by Jalali day, with an icon and color per activity type and filters.
   - A GitHub-style **calendar heatmap** of trading days, colored by net P/L (green / red,
     intensity = size). Clicking a day opens its activities and trades.
5. **عملکرد (Performance)**: the honest report card.
   - Totals: total profit (sum of winners), total loss (sum of losers), net P/L, fees paid, number of
     trades, wins / losses / breakeven.
   - Ratios: win rate, average win vs average loss, **profit factor**, **expectancy** per trade
     (Toman and R), average R, best and worst trade, longest win and loss streaks, **max drawdown**
     (Toman and %), average holding sessions.
   - Charts: P/L by day / week / month (bar, green/red); R-multiple distribution (histogram);
     cumulative P/L; P/L by symbol (top/bottom 10); P/L by setup tag and by source (scanner vs
     Telegram signal vs news vs manual); P/L by weekday; exit-reason breakdown (stop / target /
     manual / time).
   - **Discipline section**: % of trades with a stop, % that followed the plan, oversized trades,
     rule breaks, most common mistakes from the journal, and P/L of "followed plan" vs "broke plan".
   - **Overall verdict ("در کل چطور بودم؟")**: a 0–100 score with a letter grade and a one-paragraph
     Persian explanation generated from the numbers (no LLM needed, use rules). Weighting:
     expectancy 35%, profit factor 20%, max drawdown 20%, discipline 25%. Show the 3 strengths and
     the 3 biggest weaknesses with concrete numbers. For example: «۷۰٪ ضررها از معاملاتی بود که حد
     ضرر جابه‌جا شد». With fewer than 20 trades, say clearly that the sample is too small to judge.
   - Period selector: this week / month / 3 months / all / custom (Jalali), with comparison to the
     previous period.
6. **ژورنال (Journal)**: a list of closed trades and an editor for emotion, mistakes, lesson and rating.
7. **تنظیمات (Settings)**: capital, limits, fees, currency, password change, and the ingest token
   (show once, rotate).

## Ingest API (so local trading tools can sync automatically)

`POST /api/ingest` with `Authorization: Bearer <INGEST_TOKEN>` and body
`{ "mode": "paper"|"live", "orders": [...], "fills": [...], "trades": [...], "equity": [...], "activities": [...] }`.

- Upsert by `external_id`, so it's **idempotent**: sending the same payload twice changes nothing.
- Validate with zod and return counts inserted / updated / skipped.
- Also add `GET /api/export` (CSV and JSON of everything) and an import page for CSV.

The local tools are Python scripts that keep JSON files: orders (symbol, side, qty, price, stop,
target, status), closed trades (symbol, qty, buy, sell, pnl_rial, r, opened, closed, reason) and
equity snapshots `{t, equity}` in Rial. Provide a short `docs/ingest.md` with example payloads that
map those fields (convert Rial → Toman on the server).

## Design

- Calm, premium, data-dense but airy. Neutral greys with one accent (deep blue or teal). Profit is
  green (`#0f8a4b` / dark `#3ccf86`), loss is red (`#c62f2f` / dark `#ff6b6b`), and color is never
  the only signal: also use a +/− sign and arrows.
- **Light and dark themes** via CSS variables (`next-themes`), respecting the system preference, with
  a toggle in the header.
- Right-side collapsible sidebar on desktop and a bottom tab bar on mobile. Sticky header with the
  mode switch (آزمایشی / واقعی), the Jalali date and Tehran time, and the market open/closed badge.
- Tabular numbers (`font-variant-numeric: tabular-nums`). Numbers and +/− signs must render
  correctly inside RTL text: wrap numeric runs in `<bdi>` or `dir="ltr"` spans.
- Skeleton loaders, empty states with a friendly Persian message and a call to action, toasts
  for actions, keyboard-accessible, WCAG AA contrast, `prefers-reduced-motion` respected.
- No external CDNs at runtime (fonts and assets self-hosted), so it loads well from Iran.

## Quality bar

- Server Components for data reads, Server Actions for mutations, `revalidatePath` after writes.
- All money math in integers (Rial) on the server; format only in the UI.
- Unit tests (Vitest) for the performance math: profit factor, expectancy, drawdown, R, streaks,
  score. A Playwright smoke test: log in → create order → fill → close → see it in Performance.
- `README.md` (Persian and English) covering local setup, `drizzle-kit migrate`, seeding, Vercel
  deploy with Neon, and the env vars.
- When finished, run the build, lint and tests, fix every error, and report what was verified.
