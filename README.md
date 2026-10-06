# ASTRA

An automated leveraged trading bot for Binance USDⓈ-M futures. It generates
signals, runs them through a multi-layer veto chain, places orders on the
exchange, and keeps protective orders (stop-loss / take-profit / trailing) live
on the exchange side.

Python 3.10 · ~42,000 lines · 581 tests across 56 files

🇹🇷 [Türkçe README](README.tr.md)

---

## ⚠️ READ THIS FIRST — HONEST STATUS

**This bot has not been shown to be profitable.**

| | |
|---|---|
| Current mode | Binance **testnet** (play money) |
| Closed paper trades | 0 / 100 (100 required for a verdict) |
| Hypotheses measured | **9 tested, 9 rejected** |
| Statistical edge | **none found yet** |

The pipeline works end to end — signal → veto chain → order on the exchange →
SL/TP placed. That part is verified. **Profitability is not.**

`karar_kurali.py` requires 100 closed trades, expectancy > 0.10% and t > 2.0
before declaring anything. Those thresholds were written *before* seeing data
and are **not to be changed** — tuning a threshold after looking at the result
invalidates the verdict.

> **Do not run this with real money.** Nothing here is financial advice.
> Leveraged trading can lose your entire deposit. See [DISCLAIMER.md](DISCLAIMER.md).

### Why publish something that doesn't work?

Because the *measurement* is the interesting part. This repository documents
roughly 100 root causes found and fixed — and most of them were not in the
trading logic. They were in the layer that measures it: tests that could never
fail, backups that looked complete but weren't, safety gates that existed but
never closed, counters inflated 29×.

If you have ever written a backtest that looked profitable, some of this may be
useful to you.

---

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # add your own keys — this file is gitignored
python testleri_calistir.py   # 581 tests should pass
python main.py bot            # trading loop + Telegram
```

Dashboard: `http://127.0.0.1:8080` (localhost only)

### Required `.env` values

| variable | purpose |
|---|---|
| `BINANCE_API_KEY` / `_SECRET` | exchange access |
| `FUTURES_BASE_URL` | trading endpoint — **defaults to testnet** if unset |
| `LIVE_TRADING` | `false` = paper (local simulation), `true` = real orders |
| `BOT_TOKEN` / `CHAT_ID` | Telegram notifications (optional) |

⚠️ **Real money requires two deliberate steps**, and neither is the default:
`LIVE_TRADING=true` **and** `FUTURES_BASE_URL=https://fapi.binance.com`.
Omit either one and you are on testnet. An unset `FUTURES_BASE_URL` resolves to
testnet, not production — an absent value must fail safe.

Market data is unaffected by this: klines and tickers are always read from the
real exchange (`BINANCE_DATA_URL`), because testnet's thin liquidity produces
prices that never existed on the real market.

---

## How it works

```
4h candle closes
      ↓
coin_analiz()  ──  34 features · ML ensemble · regime detection (HMM)
      ↓
signal (ai_score, confidence, decision)
      ↓
┌─ VETO CHAIN ───────────────────────────────────┐
│  signal quality (AI score + confidence, per regime)
│  kill switch · circuit breaker                  │
│  cross-exchange price validation                │
│  MTF cascade   (4h vs 1d conflict)              │
│  MTF alignment (how many timeframes agree)      │
│  EdgeEngine                                      │
│  strategy engine (trend-follow / mean-reversion)│
│  minimum R/R · late entry · re-entry cooldown   │
└─────────────────────────────────────────────────┘
      ↓
order  ──  market entry + STOP_MARKET + TAKE_PROFIT_MARKET (Algo API)
      ↓
monitor  ──  SL/TP → liquidation → time stop (24h = the model's label horizon)
```

### Layout

| directory | contents |
|---|---|
| `engines/` | trade engine, paper trading, veto chain, risk, models |
| `core/` | indicators, signal scoring, regime detection |
| `data/` | Binance clients, database, multi-exchange validation |
| `execution/` | order execution, smart routing |
| `strategy/` | strategy engine, edge engine, regime adapter |
| `api/` | dashboard (single read-only endpoint) |
| `tests/` | 56 files — each one guards a specific root cause |

---

## Rules that are not negotiable

These were learned the hard way. Breaking one invalidates the measurement.

**1. Paper must mirror live exactly.**
Both paths go through the same veto chain, the same leverage, the same
thresholds. If they diverge, the 100 collected trades do not represent live
behaviour and the verdict is meaningless. Change a parameter → the collected
data is void → the counter resets.

**2. "I don't know" ≠ "nothing is wrong".**
This was the codebase's main disease. `acik_pozisyonlar()` returned `[]` on
error — meaning "no open positions". Safety-critical calls use `strict=True`
so failures raise instead of silently reading as "all clear".

**3. A green test is not evidence.**
Every veto test needs a **control test** beside it — a "never allow anything"
bug also passes every veto test. When you add a guard, deliberately break the
protection and confirm the test actually turns red.

**4. Searching source text does not lock behaviour.**
`"function_name" in source` also matches the import line, so a mutation that
deletes the *call* goes undetected. This happened four times in one session.
Write behavioural tests.

**5. Drift ≠ edge.**
In a bull sample, even random entries show positive expectancy. The correct
measure is `P(take-profit) − base rate`.

---

## Documentation

| file | contents |
|---|---|
| **`DEVAM_NOTLARI.md`** | **the real document** (Turkish) — a working journal of every root cause found, with the measurement that found it |
| `CANLI_GECIS_PROTOKOLU.md` | conditions for going to real money |
| `DENETIM_RAPORU_v55.md` | independent audit report |
| `BINANCE_ALGO_EMIR_SEMASI.md` | conditional-order API schema, derived experimentally |
| `CHANGELOG_v*.md` | version history |
| **`DISCLAIMER.md`** | financial risk — read this before running anything |

Most internal documentation is in Turkish. The code, comments and this README
are the best English entry points. Translation help is welcome.

---

## Development

```bash
python testleri_calistir.py   # full suite (581 tests)
python kontrol_4h.py          # health + trade tempo
python kontrol_kapanis.py     # exit type · funding · leverage integrity
python karar_kurali.py        # verdict (requires 100 closed trades)
```

When adding a test file, **register it in `testleri_calistir.py`** — unlisted
files are silently skipped. `tests/test_kosucu_kapsami.py` guards this.

See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a PR, and
[SECURITY.md](SECURITY.md) for anything sensitive — please do not open a
public issue for a security problem.

Licensed under the [MIT License](LICENSE).

---

## What is not in this repository

`.gitignore` excludes `.env` and all secrets, the contents of `data/` and
`saved_models/` (~8 GB of models and databases), `logs/`, order-book archives,
backup directories, and runtime state files containing real balances and
positions.

Clone it, fill in `.env.example`, and the bot collects its own data from
scratch.

---

## Current status

The project is **paused** as of September 2026. In the last measurement the
paper path opened 0 trades while the live path opened 5 — the divergence
between the two reversed direction and the cause has not been found yet.

Details: `DEVAM_NOTLARI.md` §0.44. Resume steps: §0.46.

This is a good first problem for a contributor: both paths receive the *same*
`sonuc` object in `main.py`, so an early return exists somewhere in the paper
path that the live path does not have.
