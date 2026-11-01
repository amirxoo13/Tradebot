"""Dead man's switch, built on /sapi/v1/trade/cancel-after.

The exchange cancels every pending order of the account if the bot stops
re-arming the timer. That is what protects open orders when the bot crashes,
the VPS reboots or the network drops.
"""
from __future__ import annotations

import asyncio
import logging

from .config import Config
from .rest import RestError, SunXRest

log = logging.getLogger("bot.deadman")


class DeadMansSwitch:
    def __init__(self, cfg: Config, rest: SunXRest):
        self.cfg, self.rest = cfg, rest
        self.armed = False
        self.failures = 0
        self.last_trigger_time: str | None = None
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        if self.cfg.paper:
            log.info("paper mode: dead man's switch not armed (no live orders exist)")
            return
        while not self._stop.is_set():
            try:
                d = (await self.rest.arm_deadman(self.cfg.deadman_timeout_ms)).get("data", {})
                self.last_trigger_time = d.get("trigger_time")
                if not self.armed:
                    log.info("dead man's switch armed: timeout %sms, trigger_time=%s",
                             self.cfg.deadman_timeout_ms, self.last_trigger_time)
                self.armed, self.failures = True, 0
            except RestError as exc:
                self.failures += 1
                self.armed = False
                log.error("could not arm the dead man's switch (%s): %s", self.failures, exc)
            await asyncio.sleep(self.cfg.deadman_rearm_seconds)

    async def disarm(self) -> None:
        if self.cfg.paper or not self.armed:
            return
        try:
            await self.rest.disarm_deadman()
            self.armed = False
            log.info("dead man's switch disarmed")
        except RestError as exc:
            log.error("could not disarm the dead man's switch: %s", exc)
