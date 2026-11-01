"""Configuration and hard risk limits, read from the environment.

Every number here is a limit the strategy cannot exceed. The risk engine reads
this object; nothing else is allowed to change it at runtime.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

REST_BASE = "https://api.sunx.io"
WS_MARKET = "wss://api.sunx.io/ws/v1/market"
WS_NOTIFICATION = "wss://api.sunx.io/ws/v1/notification"
WS_INDEX = "wss://api.sunx.io/ws/v1/index"


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, "") or default))
    except ValueError:
        return default


def _b(name: str, default: bool = False) -> bool:
    v = os.environ.get(name, "").strip().lower()
    return default if v == "" else v in ("1", "true", "yes", "on")


@dataclass
class Config:
    # --- credentials ---
    access_key: str = field(default_factory=lambda: os.environ.get("SUNX_ACCESS_KEY", ""))
    secret_key: str = field(default_factory=lambda: os.environ.get("SUNX_SECRET_KEY", ""))
    signature_method: str = field(default_factory=lambda: os.environ.get("SUNX_SIGNATURE_METHOD", "HmacSHA256"))

    # --- what to trade ---
    contract_code: str = field(default_factory=lambda: os.environ.get("BOT_CONTRACT", "SUN-USDT"))
    margin_mode: str = field(default_factory=lambda: os.environ.get("BOT_MARGIN_MODE", "cross"))

    # --- mode ---
    # paper: strategy runs on live data, orders are simulated and never sent.
    paper: bool = field(default_factory=lambda: not _b("BOT_LIVE", False))

    # --- hard risk limits ---
    capital_usdt: float = field(default_factory=lambda: _f("BOT_CAPITAL_USDT", 15.0))
    max_leverage: int = field(default_factory=lambda: _i("BOT_MAX_LEVERAGE", 3))
    max_position_contracts: int = field(default_factory=lambda: _i("BOT_MAX_POSITION_CONTRACTS", 0))
    max_notional_usdt: float = field(default_factory=lambda: _f("BOT_MAX_NOTIONAL_USDT", 15.0))
    stop_loss_pct: float = field(default_factory=lambda: _f("BOT_STOP_LOSS_PCT", 1.5))
    take_profit_pct: float = field(default_factory=lambda: _f("BOT_TAKE_PROFIT_PCT", 2.0))
    max_daily_loss_usdt: float = field(default_factory=lambda: _f("BOT_MAX_DAILY_LOSS_USDT", 3.0))
    max_open_orders: int = field(default_factory=lambda: _i("BOT_MAX_OPEN_ORDERS", 4))
    max_orders_per_minute: int = field(default_factory=lambda: _i("BOT_MAX_ORDERS_PER_MINUTE", 10))
    max_hold_seconds: int = field(default_factory=lambda: _i("BOT_MAX_HOLD_SECONDS", 3 * 3600))
    min_edge_over_fees: float = field(default_factory=lambda: _f("BOT_MIN_EDGE_OVER_FEES", 3.0))

    # --- dead man's switch (/sapi/v1/trade/cancel-after) ---
    deadman_timeout_ms: int = field(default_factory=lambda: _i("BOT_DEADMAN_TIMEOUT_MS", 15000))
    deadman_rearm_seconds: float = field(default_factory=lambda: _f("BOT_DEADMAN_REARM_SECONDS", 5.0))

    # --- strategy ---
    strategy: str = field(default_factory=lambda: os.environ.get("BOT_STRATEGY", "momentum"))
    log_dir: str = field(default_factory=lambda: os.environ.get("BOT_LOG_DIR", "data"))

    def validate(self) -> list[str]:
        problems = []
        if not self.paper and (not self.access_key or not self.secret_key):
            problems.append("Live mode needs SUNX_ACCESS_KEY and SUNX_SECRET_KEY.")
        if self.max_leverage < 1:
            problems.append("BOT_MAX_LEVERAGE must be >= 1.")
        if self.max_notional_usdt > self.capital_usdt * self.max_leverage:
            problems.append(
                f"BOT_MAX_NOTIONAL_USDT ({self.max_notional_usdt}) exceeds capital x leverage "
                f"({self.capital_usdt * self.max_leverage}).")
        if self.max_daily_loss_usdt >= self.capital_usdt:
            problems.append("BOT_MAX_DAILY_LOSS_USDT should be below the capital.")
        if self.margin_mode not in ("cross", "isolated"):
            problems.append("BOT_MARGIN_MODE must be 'cross' or 'isolated'.")
        return problems
