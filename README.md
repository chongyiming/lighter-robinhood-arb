# lighter-robinhood-arb

A BTC perpetual arbitrage bot between Lighter mainnet and Lighter on Robinhood Chain.

The engine, order book, order placement and hedging code come from [entropy-arb](https://github.com/your-quantguy/entropy-arb) (MIT, see `LICENSE.entropy-arb`). This repo makes two changes: both legs are zkLighter deployments (upstream's base leg is fixed to Hyperliquid), and all Hyperliquid / Entropy code has been removed.

## Signal

```
premium_bps = (Lighter price / Robinhood price - 1) * 10000

Sell Lighter / buy Robinhood   when executable premium >= midline + upper
Buy Lighter / sell Robinhood   when executable premium <= midline - lower
```

The three thresholds are fixed in `config.yaml`. Both hurdles are already net of taker fees on both legs, so one full round trip nets >= `upper + lower` bps after fees.

## Usage

```bash
pip install -r requirements.txt
cp .env.example .env          # fill in two sets of keys: mainnet LIGHTER_*, Robinhood Chain RH_*

# 1. Collect data first: no orders, no keys needed
python3 main.py --record-only --symbol BTC

# 2. Re-check the thresholds against the collected data and put them in config.yaml
python3 tools/analyze.py

# 3. Live trading (places real orders). Add --cn for a Chinese dashboard
python3 main.py --symbol BTC
```

The legs default to `--base lighter` (mainnet) and `--hedge lighter-rh` (Robinhood Chain); swap the two arguments to invert the premium direction.

There is no paper-trading mode: it's either `--record-only` data collection or live trading. **Set `max_position_usd` in `config.yaml` very small before going live.**

The two legs are separate accounts, and each needs its own API key registered.

## How it works

- **Market data**: subscribes to full-depth `order_book` on both sides (snapshot + deltas). Deltas carry a nonce; a gap means an update was lost, so the book is cleared and resubscribed — it never quotes off an incomplete book. A quiet market does not count as stale data; only a dropped connection does.
- **Order size**: walks the book level by level to find how much size is still available at the current spread, takes `take_fraction` of it, and clips it to the per-order notional cap and the position cap. It is not a fixed size.
- **Fill confirmation**: both legs send IOC orders simultaneously and wait for each order's final state on the authenticated `account_orders` channel, getting the exact filled size and average price.
- **Leg imbalance**: when net exposure exceeds `net_tolerance_base`, the excess leg is reduced with `reduce_only` (reduce only, never add, so it can't be rejected for insufficient margin) rather than topping up the short leg.
- **Position reconciliation**: real positions are checked via REST every 15 seconds; a venue that filled within the last 5 seconds is skipped, because Lighter's REST positions lag ws fills and would otherwise trigger false back-and-forth hedges.
- **Halt protection**: after 3 consecutive execution errors the engine halts; flatten manually and restart.

## Legacy scripts

`monitor.py` / `analyze.py` / `alert.py` are early top-of-book collection, backtesting and desktop alert tools that read and write `data/premium_data.csv`. They are unrelated to the new engine and kept for analysing historical data. The new engine's own recorder writes `logs/minutes.csv`, analysed by `tools/analyze.py`.
