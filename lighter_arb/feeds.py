"""Websocket order-book feed, writing into lighter_arb.book.OrderBook.

LighterBookFeed consumes the zkLighter order_book channel (snapshot + diffs,
server pings, diff-nonce gap detection — a gapped book is dropped and
resubscribed rather than traded as a fiction). Every price this bot trades on
comes straight from the exchange that will fill the order.

The book is touched on any inbound frame (connection-based freshness: a quiet
market is not stale, only a dead feed is) and reconnects with backoff.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable, Optional

try:
    from websockets.asyncio.client import connect as ws_connect
except ImportError:
    from websockets import connect as ws_connect  # type: ignore

from .book import OrderBook

log = logging.getLogger("feeds")


def _chan_id(channel: str) -> Optional[int]:
    """'order_book:32' / 'order_book/32' -> 32."""
    for sep in (":", "/"):
        if sep in channel:
            try:
                return int(channel.rsplit(sep, 1)[1])
            except ValueError:
                return None
    return None


class LighterBookFeed:
    """zkLighter order book for one market over one connection."""

    def __init__(self, name: str, ws_url: str, market_id: int, book: OrderBook,
                 notify: Callable[[], None]) -> None:
        self.name = name
        self.ws_url = ws_url
        self.market_id = market_id
        self.book = book
        self.notify = notify
        self._nonce: Optional[int] = None
        self._synced = False

    async def _subscribe(self, ws) -> None:
        await ws.send(json.dumps({"type": "subscribe",
                                  "channel": f"order_book/{self.market_id}"}))

    async def _handle_book(self, ws, msg: dict, snapshot: bool) -> None:
        if _chan_id(msg.get("channel", "")) != self.market_id:
            return
        ob = msg["order_book"]
        if snapshot:
            self._nonce = ob.get("nonce")
            self._synced = True
            self.book.apply_lighter(ob, snapshot=True)
            log.info("[%s] snapshot: %d bids / %d asks", self.name,
                     len(self.book.bids), len(self.book.asks))
            self.notify()
            return
        # diff: a skipped nonce means we lost a level update — the book is now
        # a fiction. Drop it and resubscribe rather than quote off a ghost.
        if not self._synced:
            return  # no snapshot yet (fresh connection, or one pending after a gap)
        prev, begin, end = self._nonce, ob.get("begin_nonce"), ob.get("nonce")
        if prev is not None and begin is not None and begin > prev + 1:
            log.warning("[%s] diff gap (had %s, got %s) — resubscribing",
                        self.name, prev, begin)
            self._nonce = None
            self._synced = False
            self.book.clear()
            self.notify()
            await ws.send(json.dumps({"type": "unsubscribe",
                                      "channel": f"order_book/{self.market_id}"}))
            await self._subscribe(ws)
            return
        if end is not None:
            self._nonce = end
        self.book.apply_lighter(ob, snapshot=False)
        self.notify()

    async def run(self, stop: asyncio.Event) -> None:
        backoff = 1.0
        while not stop.is_set():
            try:
                async with ws_connect(self.ws_url, max_size=2**23, open_timeout=10,
                                      ping_interval=15, ping_timeout=15) as ws:
                    log.info("[%s] connected (%s)", self.name, self.ws_url)
                    self.book.clear()
                    self._nonce = None
                    self._synced = False
                    async for raw in ws:
                        backoff = 1.0
                        msg = json.loads(raw)
                        t = msg.get("type")
                        self.book.touch()
                        if t == "update/order_book":
                            await self._handle_book(ws, msg, snapshot=False)
                        elif t == "subscribed/order_book":
                            await self._handle_book(ws, msg, snapshot=True)
                        elif t == "connected":
                            await self._subscribe(ws)
                        elif t == "ping":
                            await ws.send(json.dumps({"type": "pong"}))
                        if stop.is_set():
                            break
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("[%s] ws error: %s — reconnect in %.0fs",
                            self.name, e, backoff)
            self.book.ready = False
            self.notify()
            if stop.is_set():
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
