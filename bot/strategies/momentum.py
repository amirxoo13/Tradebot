"""Example strategy: short-term momentum from the trade tape.

This is a reference implementation so the skeleton is runnable end to end, not a
strategy with a proven edge. It only enters when the expected move is larger than
the round-trip fee by the configured multiple, which is the one rule that matters
most with small capital.
"""
from __future__ import annotations

import time

from .base import Intent, Strategy


class MomentumStrategy(Strategy):
    name = "momentum"

    def __init__(self, cfg, state, window_seconds: float = 30.0, threshold_pct: float = 0.15):
        super().__init__(cfg, state)
        self.window_seconds = window_seconds
        self.threshold_pct = threshold_pct
        self._last_entry = 0.0
        self.cooldown_seconds = 60.0

    def _window_change_pct(self) -> float | None:
        now_ms = time.time() * 1000
        pts = [t for t in self.state.trades if now_ms - t["ts"] <= self.window_seconds * 1000]
        if len(pts) < 10:
            return None
        first, last = pts[0]["price"], pts[-1]["price"]
        if not first:
            return None
        return (last - first) / first * 100

    def on_tick(self) -> Intent:
        s = self.state
        if not s.book.fresh:
            return Intent("hold", reason="stale book")

        if s.position.is_open:
            return Intent("hold", reason="position open; exits are handled by the risk engine")

        if time.time() - self._last_entry < self.cooldown_seconds:
            return Intent("hold", reason="cooldown")

        change = self._window_change_pct()
        if change is None:
            return Intent("hold", reason="not enough trades in the window yet")

        # the move must beat the fees, and the spread must not eat the edge
        need = self.threshold_pct
        if s.fee_taker is not None:
            need = max(need, abs(s.fee_taker) * 2 * 100 * self.cfg.min_edge_over_fees)
        if s.book.spread_pct > need / 2:
            return Intent("hold", reason=f"spread {s.book.spread_pct:.3f}% too wide vs need {need:.3f}%")
        if abs(change) < need:
            return Intent("hold", reason=f"move {change:.3f}% below threshold {need:.3f}%")

        self._last_entry = time.time()
        side = "buy" if change > 0 else "sell"
        return Intent(side, volume=1, order_type="market",
                      reason=f"{change:+.3f}% over {self.window_seconds:.0f}s (needed {need:.3f}%)")


def build(cfg, state):
    return MomentumStrategy(cfg, state)
