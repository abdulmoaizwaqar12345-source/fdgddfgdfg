# Forex Setup Alert Bot — Setup Guide

This bot checks EUR/USD, GBP/USD, USD/JPY, USD/CHF, USD/CAD, AUD/USD and
NZD/USD every 15 minutes, 24/7, and sends you a Telegram message the instant
your strategy's setup forms. It never places trades — alerts only.

It runs entirely on free infrastructure:
- **Data**: Twelve Data (free tier)
- **Scheduler**: GitHub Actions (free tier — runs every 15 min automatically)
- **Notifications**: Telegram

You do not need to keep any computer running. Once deployed, it runs in the
cloud forever, for free, until you turn it off.

---

## Step 1 — Get a free Twelve Data API key

1. Go to https://twelvedata.com/ and click **Sign Up** (free, no credit card).
2. After signing in, go to your **Dashboard** — you'll see an **API Key**
   near the top. Copy it somewhere safe. You'll paste it into GitHub in Step 4.

---

## Step 2 — Create your Telegram bot

1. Open Telegram (app or web) and search for **@BotFather**.
2. Send it the message `/newbot`.
3. Give it a name (anything) and a username (must end in `bot`, e.g.
   `my_forex_alerts_bot`).
4. BotFather will reply with a **token** that looks like
   `123456789:AAExampleTokenString`. Copy it — this is `TELEGRAM_BOT_TOKEN`.
5. Now find your **chat ID**:
   - Search for **@userinfobot** on Telegram and send it any message.
   - It replies with your numeric **Id** — that's your `TELEGRAM_CHAT_ID`.
6. Start a chat with the bot you just created (search its username, hit
   **Start**) — this lets it message you.

---

## Step 3 — Put this code on GitHub

1. Go to https://github.com and create a free account if you don't have one.
2. Click **New repository**. Name it e.g. `forex-alert-bot`. Set it to
   **Private** (recommended, keeps your setup private). Click **Create**.
3. On the new repo page, click **Add file → Upload files**, and drag in
   every file from this project folder (keep the folder structure —
   `.github/workflows/run-bot.yml` must stay in that exact path).
4. Click **Commit changes**.

*(If you're comfortable with git instead of the web upload, that works too —
`git init`, `git add .`, `git commit`, `git push` to a new repo.)*

---

## Step 4 — Add your secrets to GitHub

Your API key and Telegram credentials should never be pasted directly into
the code — GitHub has a secure vault for this called **Secrets**.

1. In your repo, go to **Settings → Secrets and variables → Actions**.
2. Click **New repository secret** and add each of these three, one at a time:
   - Name: `TWELVEDATA_API_KEY` → Value: (paste your key from Step 1)
   - Name: `TELEGRAM_BOT_TOKEN` → Value: (paste your token from Step 2)
   - Name: `TELEGRAM_CHAT_ID` → Value: (paste your chat ID from Step 2)

---

## Step 5 — Turn it on

1. Go to the **Actions** tab in your repo.
2. You'll see a workflow called **Forex Setup Alert Bot**. Click it.
3. If GitHub shows a banner asking to enable workflows, click **Enable**.
4. Click **Run workflow** (top right) to trigger a manual test run right now.
5. Click into the run and watch the logs — you should see each pair being
   checked, its 4H trend, and whether a signal fired. If everything's
   configured correctly, this proves the whole pipeline works.

From this point on, it runs automatically every 15 minutes, forever, with
no further action needed from you.

---

## Testing your Telegram connection separately

If you want to confirm Telegram works before the full bot runs, you can run
`test_telegram.py` on your own computer (needs Python installed) — see the
instructions inside that file. This just sends a "✅ connected" test message.

---

## What the alert looks like

```
🚨 SELL SETUP — EUR/USD

4H trend: BEARISH
15m close: 1.06778
15m EMA21: 1.06291
ATR(96,15m): 0.00023
Distance: 0.00486 (2.11x ATR)
Candle: 2026-01-10T08:30:00+00:00

This is an alert only — no trade was placed.
```

---

## Tuning the strategy

Open `main.py` and edit the constants near the top:

- `PAIRS` — add/remove currency pairs (each extra pair costs more API credits
  — see the note below on the free-tier budget).
- `ATR_MULTIPLIER` — how many ATRs of distance from EMA21(15m) counts as
  "overextended." Currently `1.0`. Raise it for fewer, more extreme setups;
  lower it for more frequent, less extreme ones.
- `EMA_FAST` / `EMA_SLOW` — currently 9 and 21, matching your strategy.
- `ATR_PERIOD` — currently 96, matching your strategy.

After editing, just commit the change back to GitHub — the next scheduled
run will use the new settings automatically.

---

## Free-tier budget (important)

Twelve Data's free plan allows **800 API calls/day**. This bot uses **1 call
per pair per 15-minute check** (it derives the 4H trend from the same 15m
data instead of a second call, to save credits).

- 7 pairs × 96 checks/day = **672 calls/day** — safely under the 800 limit.
- If you add more pairs later, keep pairs × 96 ≤ 800, or upgrade your Twelve
  Data plan.

---

## How "one alert only" works

The bot remembers (in `state.json`, auto-committed back to your repo after
each run) the timestamp of the last candle it already alerted on, per pair
and direction. It only messages you again once a genuinely new qualifying
candle closes — not on every run while conditions remain true.

---

## Known nuances worth knowing

- **4H candle boundaries**: this bot builds 4H candles by grouping four
  consecutive 15m candles starting at 00:00 UTC (standard convention). If
  your own charting platform anchors 4H bars differently (some brokers start
  the trading day at a different UTC hour), the 4H trend reading could
  occasionally differ slightly near session boundaries.
- **"Overextended" persisting across multiple candles**: if price stays
  stretched away from EMA21 for several consecutive 15m candles, you could
  get more than one alert in a short window (each on a genuinely new candle).
  If you'd rather have a cooldown (e.g. "don't re-alert the same pair+direction
  within 4 hours"), that's a small code change — just ask.
