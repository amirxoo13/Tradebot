"""Unit tests for the risk engine, executor and strategy. No network, no orders."""
import asyncio, json, os, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.config import Config
from bot.state import State
from bot.risk import RiskEngine
from bot.executor import Executor
from bot.strategies.momentum import MomentumStrategy

TMP = tempfile.mkdtemp()


def make(capital=15.0, lev=3, contract_size=100.0, price=0.0151, **kw):
    os.environ["BOT_LOG_DIR"] = TMP
    cfg = Config(capital_usdt=capital, max_leverage=lev, paper=True,
                 contract_code="SUN-USDT", log_dir=TMP, **kw)
    st = State("SUN-USDT")
    st.contract_size = contract_size
    st.min_volume = 1.0
    st.max_leverage = 20.0
    st.book.bid, st.book.ask, st.book.ts = price * 0.999, price * 1.001, time.time()
    return cfg, st, RiskEngine(cfg, st)


def test_max_contracts_from_capital():
    _, _, r = make()                                   # 15 USDT, 1 contract = 1.51 USDT
    assert r.max_contracts() == int(15.0 // (0.0151 * 100)), r.max_contracts()


def test_rejects_when_one_contract_unaffordable():
    cfg, st, r = make(contract_size=0.001, price=77700.0)   # BTC-like
    assert r.max_contracts() == 0
    d = r.check({"volume": 1})
    assert not d and "cannot afford" in d.reason, d.reason


def test_rejects_stale_book():
    _, st, r = make()
    st.book.ts = time.time() - 60
    d = r.check({"volume": 1})
    assert not d and "stale" in d.reason


def test_rejects_over_position_cap():
    _, st, r = make()
    st.position.volume = r.max_contracts()
    d = r.check({"volume": 1})
    assert not d and "exceeds the cap" in d.reason, d.reason


def test_rejects_over_leverage():
    cfg, st, r = make(lev=1)
    d = r.check({"volume": r.max_contracts() + 5})
    assert not d


def test_rate_limit():
    cfg, st, r = make(max_orders_per_minute=2)
    assert r.check({"volume": 1}); r.record({})
    assert r.check({"volume": 1}); r.record({})
    d = r.check({"volume": 1})
    assert not d and "rate limit" in d.reason


def test_daily_loss_halts():
    cfg, st, r = make(max_daily_loss_usdt=2.0)
    st.add_realized(-2.5)
    d = r.check({"volume": 1})
    assert not d and r.halted


def test_closing_allowed_even_when_capped():
    _, st, r = make()
    st.position.volume = r.max_contracts()
    assert r.check({"volume": 1, "reduce_only": True})


def test_stop_loss_and_take_profit():
    cfg, st, r = make(stop_loss_pct=1.0, take_profit_pct=2.0)
    st.position.volume = 1; st.position.position_side = "long"
    st.position.entry_price = 0.0151; st.position.opened_at = time.time()
    st.book.bid = st.book.ask = 0.0151 * 0.98                    # -2%
    assert "stop loss" in (r.exit_reason() or "")
    st.book.bid = st.book.ask = 0.0151 * 1.03                    # +3%
    assert "take profit" in (r.exit_reason() or "")
    st.book.bid = st.book.ask = 0.0151
    assert r.exit_reason() is None


def test_max_hold_time():
    cfg, st, r = make(max_hold_seconds=10)
    st.position.volume = 1; st.position.position_side = "long"
    st.position.entry_price = 0.0151; st.position.opened_at = time.time() - 60
    assert "max hold" in (r.exit_reason() or "")


def test_fee_threshold():
    cfg, st, r = make(min_edge_over_fees=3.0)
    st.fee_taker = 0.0005
    assert abs(r.fee_threshold_pct() - 0.0005 * 2 * 100 * 3) < 1e-9


def test_strategy_holds_on_wide_spread():
    cfg, st, _ = make()
    st.fee_taker = 0.0005
    st.book.bid, st.book.ask = 0.0150, 0.0152          # ~1.3% spread
    now = time.time() * 1000
    for i in range(20):
        st.trades.append({"price": 0.0151 * (1 + i * 0.0005), "amount": 1,
                          "direction": "buy", "ts": now - (20 - i) * 500})
    i = MomentumStrategy(cfg, st).on_tick()
    assert i.action == "hold" and "spread" in i.reason, i.reason


def test_strategy_fires_on_momentum():
    cfg, st, _ = make()
    st.fee_taker = 0.00005                              # tight fees
    st.book.bid, st.book.ask = 0.015100, 0.015101       # ~0.007% spread
    st.book.ts = time.time()
    now = time.time() * 1000
    for i in range(30):
        st.trades.append({"price": 0.0151 * (1 + i * 0.0004), "amount": 1,
                          "direction": "buy", "ts": now - (30 - i) * 500})
    i = MomentumStrategy(cfg, st).on_tick()
    assert i.action == "buy" and i.volume == 1, (i.action, i.reason)
    j = MomentumStrategy(cfg, st)
    st.trades.clear()
    for k in range(30):
        st.trades.append({"price": 0.0151 * (1 - k * 0.0004), "amount": 1,
                          "direction": "sell", "ts": now - (30 - k) * 500})
    assert j.on_tick().action == "sell"


def test_paper_executor_sends_nothing_and_journals():
    cfg, st, r = make()
    ex = Executor(cfg, st, r, rest=None)                # rest unused in paper mode
    res = asyncio.run(ex.submit("buy", 1, note="unit test"))
    assert res["ok"] and res["paper"] and res["fill_price"] == st.book.ask
    rec = [json.loads(l) for l in (Path(TMP) / "orders.jsonl").read_text().splitlines()]
    assert rec[-1]["event"] == "paper_fill" and rec[-1]["mode"] == "paper"


def test_client_order_ids_are_unique_and_in_range():
    cfg, st, r = make()
    ex = Executor(cfg, st, r, rest=None)
    ids = {ex.build_order("buy", 1)["client_order_id"] for _ in range(500)}
    assert len(ids) == 500
    assert all(1 <= int(i) <= 9223372036854775807 for i in ids)


def test_rejected_order_is_journalled_and_not_sent():
    cfg, st, r = make(contract_size=0.001, price=77700.0)
    ex = Executor(cfg, st, r, rest=None)
    res = asyncio.run(ex.submit("buy", 1))
    assert not res["ok"] and ex.sent == 0 and ex.rejected == 1


def test_config_validation_catches_bad_limits():
    c = Config(capital_usdt=15, max_leverage=3, max_notional_usdt=1000, paper=True)
    assert any("exceeds capital" in p for p in c.validate())
    c2 = Config(capital_usdt=15, max_daily_loss_usdt=20, paper=True)
    assert any("daily_loss" in p.lower() for p in c2.validate())
    c3 = Config(paper=False, access_key="", secret_key="")
    assert any("Live mode" in p for p in c3.validate())


if __name__ == "__main__":
    fails = 0
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            try:
                f(); print("PASS", n)
            except Exception as e:
                fails += 1; print("FAIL", n, "->", type(e).__name__, e)
    print("failures:", fails)
    sys.exit(1 if fails else 0)
