"""REST calls the bot needs, built on the documented signing procedure."""
from __future__ import annotations

import json
import logging

import httpx

from .config import REST_BASE, Config
from .signing import build_signed_params

log = logging.getLogger("bot.rest")

# Endpoints verified against the live API to work WITHOUT a signature, even though the
# docs mark them "Signature verification: Yes" (both returned code 200 unsigned):
UNSIGNED_DESPITE_DOCS = {"/sapi/v1/public/risk/limit", "/sapi/v1/public/multi_assets_margin"}

PUBLIC_PREFIXES = ("/sapi/v1/public/", "/sapi/v1/market/", "/sapi/v1/index/")


class RestError(RuntimeError):
    def __init__(self, message: str, payload: dict | None = None):
        super().__init__(message)
        self.payload = payload or {}


class SunXRest:
    def __init__(self, cfg: Config, timeout: float = 15.0):
        self.cfg = cfg
        self.base = REST_BASE
        self.host = httpx.URL(REST_BASE).host
        self._c = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._c.aclose()

    def _is_public(self, path: str) -> bool:
        return path in UNSIGNED_DESPITE_DOCS or path.startswith(PUBLIC_PREFIXES)

    async def _request(self, method: str, path: str, params: dict | None = None,
                       body: dict | list | None = None, signed: bool | None = None) -> dict:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        signed = (not self._is_public(path)) if signed is None else signed
        if signed:
            if not self.cfg.access_key or not self.cfg.secret_key:
                raise RestError(f"{path} needs API keys but none are configured.")
            query = build_signed_params(
                method=method, host=self.host, sign_path=path,
                access_key=self.cfg.access_key, secret_key=self.cfg.secret_key,
                signature_method=self.cfg.signature_method,
                # docs: GET signs every parameter, POST signs only the auth parameters
                business_params=params if method == "GET" else None,
            )
        else:
            query = params
        content = json.dumps(body) if body is not None and method != "GET" else None
        r = await self._c.request(method, self.base + path, params=query,
                                  headers={"Content-Type": "application/json"}, content=content)
        try:
            payload = r.json()
        except Exception:
            raise RestError(f"{path}: non-JSON response ({r.status_code})", {"text": r.text[:400]})
        code = str(payload.get("code", "")) or ""
        status = str(payload.get("status", "")).lower()
        if r.status_code >= 400 or status == "error" or (code and code not in ("200", "0")):
            raise RestError(f"{path} rejected: {payload.get('message') or payload.get('err-msg') or payload}",
                            payload)
        return payload

    # ---------------- public ----------------
    async def contract_info(self, contract_code: str) -> dict:
        d = await self._request("GET", "/sapi/v1/public/contract_info",
                                {"contract_code": contract_code, "business_type": "all"})
        items = d.get("data") or []
        if not items:
            raise RestError(f"No contract info for {contract_code}")
        return items[0]

    async def risk_limit(self, contract_code: str) -> dict:
        d = await self._request("GET", "/sapi/v1/public/risk/limit",
                                {"contract_code": contract_code}, signed=False)
        return (d.get("data") or [{}])[0]

    async def bbo(self, contract_code: str) -> dict:
        d = await self._request("GET", "/sapi/v1/market/bbo", {"contract_code": contract_code})
        return (d.get("ticks") or [{}])[0]

    async def klines(self, contract_code: str, period: str = "1min", size: int = 200) -> list:
        d = await self._request("GET", "/sapi/v1/market/history/kline",
                                {"contract_code": contract_code, "period": period, "size": str(size)})
        return d.get("data") or []

    # ---------------- private ----------------
    async def account_balance(self) -> dict:
        return (await self._request("GET", "/sapi/v1/account/balance")).get("data", {})

    async def fee_rate(self, contract_code: str) -> dict:
        d = await self._request("POST", "/sapi/v1/account/fee_rate", body={"contract_code": contract_code})
        data = d.get("data")
        return (data[0] if isinstance(data, list) and data else data) or {}

    async def positions(self, contract_code: str | None = None) -> list:
        d = await self._request("GET", "/sapi/v1/trade/position/opens",
                                {"contract_code": contract_code})
        data = d.get("data")
        return data if isinstance(data, list) else ([data] if data else [])

    async def open_orders(self, contract_code: str) -> list:
        d = await self._request("GET", "/sapi/v1/trade/order/opens", {"contract_code": contract_code})
        data = d.get("data")
        if isinstance(data, dict):
            data = data.get("orders") or data.get("data") or []
        return data or []

    async def set_leverage(self, contract_code: str, lever_rate: int, margin_mode: str) -> dict:
        return await self._request("POST", "/sapi/v1/position/lever", body={
            "contract_code": contract_code, "lever_rate": lever_rate, "margin_mode": margin_mode})

    async def place_order(self, order: dict) -> dict:
        return (await self._request("POST", "/sapi/v1/trade/order", body=order)).get("data", {})

    async def cancel_order(self, contract_code: str, order_id: str | None = None,
                           client_order_id: str | None = None) -> dict:
        return await self._request("POST", "/sapi/v1/trade/cancel_order", body={
            "contract_code": contract_code, "order_id": order_id, "client_order_id": client_order_id})

    async def cancel_all(self, contract_code: str) -> dict:
        return await self._request("POST", "/sapi/v1/trade/cancel_all_orders",
                                   body={"contract_code": contract_code})

    async def close_position_market(self, contract_code: str, position_side: str | None = None) -> dict:
        body = {"contract_code": contract_code, "margin_mode": self.cfg.margin_mode}
        if position_side:
            body["position_side"] = position_side
        return await self._request("POST", "/sapi/v1/trade/position", body=body)

    async def arm_deadman(self, timeout_ms: int) -> dict:
        """/sapi/v1/trade/cancel-after - the exchange cancels every pending order if the
        bot stops re-arming this. on_off='1' enables, '0' disables."""
        return await self._request("POST", "/sapi/v1/trade/cancel-after",
                                   body={"on_off": "1", "time_out": str(timeout_ms)})

    async def disarm_deadman(self) -> dict:
        return await self._request("POST", "/sapi/v1/trade/cancel-after", body={"on_off": "0"})
