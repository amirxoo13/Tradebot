"""Strategy interface.

A strategy only reads state and returns an intent. It never sends an order and
never touches the risk limits - the risk engine decides whether an intent is
allowed, and the executor sends it.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..config import Config
from ..state import State


@dataclass
class Intent:
    action: str                    # "buy" | "sell" | "close" | "hold"
    volume: int = 0                # contracts
    order_type: str = "market"
    price: float | None = None
    reason: str = ""


class Strategy:
    name = "base"

    def __init__(self, cfg: Config, state: State):
        self.cfg, self.state = cfg, state

    def on_tick(self) -> Intent:
        return Intent("hold", reason="base strategy does nothing")
