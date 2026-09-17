#!/usr/bin/env python3
"""Count band triggers in the premium CSVs written by monitor.py.

    midline = median(mid_prem)                        (or --midline)
    sell when sell_prem >= midline + upper            # sell Lighter, buy Robinhood
    buy  when buy_prem  <= midline - lower            # buy Lighter, sell Robinhood

Also simulates the band strategy with a 1-unit position cap: a sell from flat
opens a short that the next buy closes (and vice versa). Round-trip profit in
bps = sell_prem at the sell - buy_prem at the buy.
"""

import argparse
import csv
import statistics
from pathlib import Path


def load_rows(data_dir):
    rows = []
    for path in sorted(data_dir.glob("premium_data.csv")):
        with path.open(newline="") as f:
            for r in csv.DictReader(f):
                rows.append({
                    "time": r["time_utc"][:19].replace("T", " "),
                    "sell_prem": float(r["sell_prem"]),
                    "buy_prem": float(r["buy_prem"]),
                    "mid_prem": float(r["mid_prem"]),
                })
    return rows


def count_triggers(hits):
    """Number of times hits goes from False to True (a run of consecutive hits counts once)."""
    return sum(1 for prev, cur in zip([False] + hits, hits) if cur and not prev)


def simulate(rows, sell_level, buy_level):
    pos, entry, trades, pnls = 0, None, [], []
    for r in rows:
        if r["sell_prem"] >= sell_level and pos > -1:
            pos -= 1
            if pos == 0:
                pnls.append(r["sell_prem"] - entry)
                trades.append((r["time"], "sell (close long) ", r["sell_prem"], pnls[-1]))
            else:
                entry = r["sell_prem"]
                trades.append((r["time"], "sell (open short) ", r["sell_prem"], None))
        if r["buy_prem"] <= buy_level and pos < 1:
            pos += 1
            if pos == 0:
                pnls.append(entry - r["buy_prem"])
                trades.append((r["time"], "buy  (close short)", r["buy_prem"], pnls[-1]))
            else:
                entry = r["buy_prem"]
                trades.append((r["time"], "buy  (open long)  ", r["buy_prem"], None))
    return trades, pnls, pos


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--upper", type=float, default=3.0, help="bps above midline to sell")
    p.add_argument("--lower", type=float, default=3.0, help="bps below midline to buy")
    p.add_argument("--midline", type=float, help="fixed midline in bps (default: median of mid_prem)")
    p.add_argument("--data-dir", type=Path, default=Path("data"))
    args = p.parse_args()

    rows = load_rows(args.data_dir)
    if not rows:
        raise SystemExit(f"no premium_*.csv rows in {args.data_dir}/")

    mids = [r["mid_prem"] for r in rows]
    median, mean = statistics.median(mids), statistics.mean(mids)
    midline = median if args.midline is None else args.midline
    sell_level = midline + args.upper
    buy_level = midline - args.lower

    sell_hits = [r["sell_prem"] >= sell_level for r in rows]
    buy_hits = [r["buy_prem"] <= buy_level for r in rows]
    n = len(rows)

    print(f"rows {n}  {rows[0]['time']} -> {rows[-1]['time']} UTC")
    source = "fixed" if args.midline is not None else "median of mid_prem"
    print(f"midline {midline:+.3f} bps ({source}; data median {median:+.3f}, mean {mean:+.3f})")
    print(f"sell when sell_prem >= {sell_level:+.3f}   buy when buy_prem <= {buy_level:+.3f}")
    print()
    print(f"{'':10}{'hit rows':>10}{'% time':>10}{'triggers':>10}")
    for name, hits in (("sell side", sell_hits), ("buy side", buy_hits)):
        print(f"{name:10}{sum(hits):>10}{sum(hits) / n:>10.2%}{count_triggers(hits):>10}")

    trades, pnls, pos = simulate(rows, sell_level, buy_level)
    print()
    for time, action, prem, pnl in trades:
        tail = f"  round trip {pnl:+.3f} bps" if pnl is not None else ""
        print(f"  {time}  {action}  prem {prem:+.3f}{tail}")
    print(f"sim: trades {len(trades)}, round trips {len(pnls)}, pnl {sum(pnls):+.3f} bps, open position {pos:+d}")


if __name__ == "__main__":
    main()
