#!/usr/bin/env python3
"""Lighter (mainnet) x Lighter on Robinhood Chain BTC premium recorder.

Streams best bid/ask from both venues over the public `ticker/{market_id}`
WebSocket channel (no API key needed) and, every --interval seconds
(default 60), records:

    sell_prem = (L_bid / R_ask - 1) * 1e4    # sell Lighter, buy Robinhood
    buy_prem  = (L_ask / R_bid - 1) * 1e4    # buy Lighter, sell Robinhood
    mid_prem  = (sell_prem + buy_prem) / 2

Each tick is appended to <out-dir>/premium_YYYYMMDD.csv (UTC date).
"""

import argparse
import asyncio
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import websockets

CSV_FIELDS = [
    "ts", "time_utc",
    "l_bid", "l_ask", "r_bid", "r_ask",
    "sell_prem", "buy_prem", "mid_prem",
    "l_age_ms", "r_age_ms",
]


def log(msg):
    print(f"{datetime.now(timezone.utc):%H:%M:%S}  {msg}", file=sys.stderr, flush=True)


class Quote:
    """Latest BBO from one venue; cleared while the connection is down."""

    def __init__(self, name):
        self.name = name
        self.bid = self.ask = self.recv_ts = None

    def clear(self):
        self.bid = self.ask = self.recv_ts = None


async def stream_ticker(ws_url, market_id, quote, ping_s=20):
    channel = f"ticker/{market_id}"
    # Iterating connect() reconnects with backoff; ping frames satisfy the 2-minute keepalive
    # and detect a dead connection within ~2 * ping_s.
    async for ws in websockets.connect(ws_url, ping_interval=ping_s, ping_timeout=ping_s):
        try:
            await ws.send(json.dumps({"type": "subscribe", "channel": channel}))
            log(f"{quote.name}: subscribed {channel}")
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("type") not in ("subscribed/ticker", "update/ticker"):
                    continue
                t = msg.get("ticker") or {}
                try:
                    quote.bid = float(t["b"]["price"])
                    quote.ask = float(t["a"]["price"])
                except (KeyError, TypeError, ValueError):
                    quote.clear()  # one side of the book is empty
                    continue
                quote.recv_ts = time.time()
        except websockets.ConnectionClosed as e:
            log(f"{quote.name}: disconnected ({e}), reconnecting")
            quote.clear()


class CsvWriter:
    def __init__(self, out_dir):
        self.out_dir = out_dir
        self.path = None
        self.file = None
        self.writer = None

    def write(self, row):
        path = self.out_dir / f"premium_data.csv"
        if path != self.path:
            if self.file:
                self.file.close()
            new = not path.exists()
            self.file = path.open("a", newline="")
            self.writer = csv.DictWriter(self.file, fieldnames=CSV_FIELDS)
            if new:
                self.writer.writeheader()
            self.path = path
        self.writer.writerow(row)
        self.file.flush()

    def close(self):
        if self.file:
            self.file.close()


def sample(lq, rq, now):
    """Build one CSV row from the latest quotes, or None if either venue has no quote."""
    if lq.recv_ts is None or rq.recv_ts is None:
        return None
    sell_prem = (lq.bid / rq.ask - 1) * 1e4
    buy_prem = (lq.ask / rq.bid - 1) * 1e4
    return {
        "ts": round(now, 3),
        "time_utc": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="milliseconds"),
        "l_bid": lq.bid, "l_ask": lq.ask, "r_bid": rq.bid, "r_ask": rq.ask,
        "sell_prem": round(sell_prem, 3),
        "buy_prem": round(buy_prem, 3),
        "mid_prem": round((sell_prem + buy_prem) / 2, 3),
        "l_age_ms": round((now - lq.recv_ts) * 1000),
        "r_age_ms": round((now - rq.recv_ts) * 1000),
    }


def print_row(row):
    print(
        f"{row['time_utc'][11:19]}  "
        f"L {row['l_bid']:.1f}/{row['l_ask']:.1f}  "
        f"R {row['r_bid']:.1f}/{row['r_ask']:.1f}  "
        f"sell {row['sell_prem']:+7.2f}  buy {row['buy_prem']:+7.2f}  mid {row['mid_prem']:+7.2f}",
        flush=True,
    )


async def sample_loop(lq, rq, writer, args):
    loop = asyncio.get_running_loop()
    next_t = loop.time()
    while True:
        next_t += args.interval
        delay = next_t - loop.time()
        if delay > 0:
            await asyncio.sleep(delay)
        else:
            next_t = loop.time()
        row = sample(lq, rq, time.time())
        if row is None:
            missing = [q.name for q in (lq, rq) if q.recv_ts is None]
            log(f"waiting for quotes: {', '.join(missing)}")
            continue
        writer.write(row)
        print_row(row)


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--interval", type=float, default=60.0, help="seconds between samples (default 60 = one row per minute)")
    p.add_argument("--out-dir", type=Path, default=Path("data"))
    p.add_argument("--lighter-ws", default="wss://mainnet.zklighter.elliot.ai/stream")
    p.add_argument("--lighter-market-id", type=int, default=1, help="1 = BTC perp")
    p.add_argument("--rh-ws", default="wss://api.rh.lighter.xyz/stream")
    p.add_argument("--rh-market-id", type=int, default=1, help="1 = BTC perp")
    return p.parse_args()


async def run(args):
    args.out_dir.mkdir(parents=True, exist_ok=True)
    lq, rq = Quote("lighter"), Quote("robinhood")
    writer = CsvWriter(args.out_dir)
    try:
        await asyncio.gather(
            stream_ticker(args.lighter_ws, args.lighter_market_id, lq),
            stream_ticker(args.rh_ws, args.rh_market_id, rq),
            sample_loop(lq, rq, writer, args),
        )
    finally:
        writer.close()


def main():
    try:
        asyncio.run(run(parse_args()))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
