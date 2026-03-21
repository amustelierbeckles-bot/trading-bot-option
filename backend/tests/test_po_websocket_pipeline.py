"""
Tests: pipeline ticks → CandleBuffer → scanner (auto_exec pattern).

Plan: plan_tests_ticks-scanner — T1.x, P3.x, S2.x
"""
import sys
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.append(str(Path(__file__).parent.parent))

from data_provider import CandleData, IndicatorSet
from po_websocket import (
    CandleBuffer,
    OTC_SYMBOL_MAP,
    POWebSocketProvider,
)


# ── Mirror of auto_exec _auto_scan_loop PO branch (no app.state) ──────────────


def build_indicators_map_from_po(po_prov: POWebSocketProvider, symbols: list) -> dict:
    """Same logic as auto_exec.py when building indicators from PO buffers."""
    indicators_map: dict = {}
    if not po_prov or po_prov._kill_switch_active:
        return indicators_map
    for sym in symbols:
        if not po_prov.is_ready(sym):
            continue
        candles_raw = po_prov.get_candles(sym)
        if not candles_raw:
            continue
        candles = [
            CandleData(
                time=datetime.utcfromtimestamp(c["time"]).strftime("%Y-%m-%d %H:%M:%S"),
                open=c["open"],
                high=c["high"],
                low=c["low"],
                close=c["close"],
            )
            for c in candles_raw
        ]
        ind = IndicatorSet()
        ind.compute(candles)
        ind.last_candle_time = candles[-1].time if candles else ""
        indicators_map[sym] = ind
    return indicators_map


def seed_buffer_one_candle_per_minute(buf: CandleBuffer, start_ts: float, n: int, base_price: float = 1.0820):
    """Append n 1-minute candles by advancing timestamp 60s each update."""
    for i in range(n):
        ts = start_ts + i * 60
        buf.update(base_price + i * 0.00001, ts)


# =============================================================================
# 1. PIPELINE TICKS → BUFFER (T1.x)
# =============================================================================


class TestCandleBufferUpdate:
    """T1.4 — velas en minutos distintos; buffer no congelado."""

    def test_t1_4_candles_grow_across_minutes(self):
        buf = CandleBuffer()
        t0 = 1_700_000_000
        seed_buffer_one_candle_per_minute(buf, t0, 5, 1.0)
        assert len(buf.candles) == 5
        assert buf.candles[-1]["close"] == pytest.approx(1.0 + 4 * 0.00001)
        assert buf.last_price == pytest.approx(1.0 + 4 * 0.00001)

    def test_t1_4_same_minute_updates_single_candle(self):
        buf = CandleBuffer()
        t = 1_700_000_000
        buf.update(1.0, t)
        buf.update(1.1, t + 10)
        assert len(buf.candles) == 1
        assert buf.candles[-1]["close"] == 1.1


@pytest.mark.asyncio
class TestHandleBinaryPrice:
    """T1.1, T1.2, T1.3, T1.5, T1.6"""

    async def test_t1_1_writes_tick_to_buffer(self):
        prov = POWebSocketProvider()
        # 1.0825 * 1e6 = 1082500
        raw = b'["#EURUSD_otc",1082500]'
        await prov._handle_binary_price(raw)
        assert prov._buffers["OTC_EURUSD"].last_price == pytest.approx(1.0825)

    async def test_t1_2_last_update_advances(self):
        prov = POWebSocketProvider()
        t0, t1 = 1_700_000_100.0, 1_700_000_200.0
        raw1 = b'["#EURUSD_otc",1082500]'
        raw2 = b'["#EURUSD_otc",1082600]'
        with patch("po_websocket.time.time", side_effect=[t0, t1]):
            await prov._handle_binary_price(raw1)
            assert prov._buffers["OTC_EURUSD"].last_update == t0
            await prov._handle_binary_price(raw2)
            assert prov._buffers["OTC_EURUSD"].last_update == t1

    async def test_t1_3_last_price_changes(self):
        prov = POWebSocketProvider()
        await prov._handle_binary_price(b'["#EURUSD_otc",1000000]')
        await prov._handle_binary_price(b'["#EURUSD_otc",2000000]')
        assert prov._buffers["OTC_EURUSD"].last_price == 2.0

    async def test_t1_5_unknown_symbol_does_not_touch_known_buffers(self):
        prov = POWebSocketProvider()
        await prov._handle_binary_price(b'["#EURUSD_otc",1082500]')
        before = prov._buffers["OTC_EURUSD"].last_price
        await prov._handle_binary_price(b'["#ZZZZZZ_otc",999999999]')
        assert prov._buffers["OTC_EURUSD"].last_price == before

    async def test_t1_6_invalid_json_no_crash(self):
        prov = POWebSocketProvider()
        await prov._handle_binary_price(b"not valid json {{{")
        assert prov._buffers["OTC_EURUSD"].last_price == 0.0


# =============================================================================
# 3. PIPELINE SUSCRIPCIÓN → 20 PARES (P3.x)
# =============================================================================


def test_p3_1_otc_symbol_map_has_twenty_unique_keys():
    assert len(OTC_SYMBOL_MAP) == 20
    keys = list(OTC_SYMBOL_MAP.keys())
    assert len(set(keys)) == 20
    assert all(k.startswith("OTC_") for k in keys)


@pytest.mark.asyncio
async def test_p3_2_subscribe_pairs_sends_twenty_messages():
    prov = POWebSocketProvider()
    ws = AsyncMock()
    with patch("po_websocket.random.uniform", return_value=0):
        await prov._subscribe_pairs(ws)
    assert ws.send.await_count == 20
    for call in ws.send.await_args_list:
        payload = call.args[0]
        assert "42" in payload or payload.startswith("42")
        assert "subscribeSymbol" in payload


@pytest.mark.asyncio
async def test_p3_3_p3_4_buffers_isolated_no_cross_contamination():
    prov = POWebSocketProvider()
    await prov._handle_binary_price(b'["#EURUSD_otc",1082500]')
    await prov._handle_binary_price(b'["#GBPUSD_otc",1250000]')
    assert prov._buffers["OTC_EURUSD"].last_price == pytest.approx(1.0825)
    assert prov._buffers["OTC_GBPUSD"].last_price == 1.25
    gbp_before = list(prov.get_candles("OTC_GBPUSD"))
    await prov._handle_binary_price(b'["#EURUSD_otc",1090000]')
    assert prov._buffers["OTC_GBPUSD"].last_price == 1.25
    assert prov.get_candles("OTC_GBPUSD") == gbp_before


@pytest.mark.asyncio
async def test_p3_5_buffers_persist_when_not_reinstantiated():
    prov = POWebSocketProvider()
    await prov._handle_binary_price(b'["#EURUSD_otc",1082500]')
    prov.is_connected = False
    assert prov._buffers["OTC_EURUSD"].last_price == pytest.approx(1.0825)
    assert prov.get_candles("OTC_EURUSD")


@pytest.mark.asyncio
async def test_p3_5_new_provider_resets_buffers():
    """Dos constructores POWebSocketProvider() distintos → buffers independientes."""
    p1 = POWebSocketProvider()
    await p1._handle_binary_price(b'["#EURUSD_otc",1082500]')
    p2 = POWebSocketProvider()
    assert p2._buffers["OTC_EURUSD"].last_price == 0.0


def test_init_po_provider_preserves_buffers_on_reinit():
    """Segundo init_po_provider reutiliza _buffers del singleton anterior."""
    import po_websocket as mod

    mod._po_provider = None
    p1 = mod.init_po_provider("ssid-a")
    p1._buffers["OTC_EURUSD"].last_price = 1.2345
    p2 = mod.init_po_provider("ssid-b")
    assert p2 is not p1
    assert p2._buffers["OTC_EURUSD"].last_price == pytest.approx(1.2345)
    mod._po_provider = None


# =============================================================================
# 2. PIPELINE BUFFER → SCANNER (S2.x)
# =============================================================================


class TestGetLatestPriceAndIsReady:
    """S2.3, S2.4, S2.5, S2.6"""

    def test_s2_3_get_latest_price_none_when_stale(self):
        prov = POWebSocketProvider()
        buf = prov._buffers["OTC_EURUSD"]
        buf.last_price = 1.1
        buf.last_update = time.time() - 200
        assert prov.get_latest_price("OTC_EURUSD", max_age_seconds=180) is None

    def test_s2_4_get_latest_price_fresh_returns_price(self):
        prov = POWebSocketProvider()
        buf = prov._buffers["OTC_EURUSD"]
        buf.last_price = 1.2345
        buf.last_update = time.time() - 10
        assert prov.get_latest_price("OTC_EURUSD", max_age_seconds=180) == pytest.approx(1.2345)

    def test_s2_5_is_ready_false_below_thirty_candles(self):
        prov = POWebSocketProvider()
        seed_buffer_one_candle_per_minute(prov._buffers["OTC_EURUSD"], time.time() - 3600, 10)
        assert prov.is_ready("OTC_EURUSD") is False

    def test_s2_6_is_ready_true_with_thirty_candles(self):
        prov = POWebSocketProvider()
        seed_buffer_one_candle_per_minute(prov._buffers["OTC_EURUSD"], time.time() - 4000, 30)
        assert prov.is_ready("OTC_EURUSD") is True


class TestBuildIndicatorsFromPo:
    """S2.1, S2.2, S2.7"""

    def test_s2_7_only_ready_pairs_in_indicators_map(self):
        prov = POWebSocketProvider()
        seed_buffer_one_candle_per_minute(prov._buffers["OTC_EURUSD"], time.time() - 5000, 30)
        seed_buffer_one_candle_per_minute(prov._buffers["OTC_GBPUSD"], time.time() - 5000, 30)
        symbols = list(OTC_SYMBOL_MAP.keys())
        m = build_indicators_map_from_po(prov, symbols)
        assert len(m) == 2
        assert "OTC_EURUSD" in m and "OTC_GBPUSD" in m

    def test_s2_1_second_cycle_reflects_buffer_mutation(self):
        prov = POWebSocketProvider()
        t0 = time.time() - 4000
        seed_buffer_one_candle_per_minute(prov._buffers["OTC_EURUSD"], t0, 30, 1.0)
        symbols = ["OTC_EURUSD"]
        m1 = build_indicators_map_from_po(prov, symbols)
        cci1 = m1["OTC_EURUSD"].cci
        # New minute with very different price moves CCI
        prov._buffers["OTC_EURUSD"].update(2.5, t0 + 30 * 60 + 60)
        m2 = build_indicators_map_from_po(prov, symbols)
        cci2 = m2["OTC_EURUSD"].cci
        assert m1["OTC_EURUSD"] is not m2["OTC_EURUSD"]
        assert cci1 != cci2 or m2["OTC_EURUSD"].price == pytest.approx(2.5)

    def test_s2_2_indicators_map_rebuilt_each_call_new_instances(self):
        prov = POWebSocketProvider()
        seed_buffer_one_candle_per_minute(prov._buffers["OTC_EURUSD"], time.time() - 4000, 30)
        symbols = ["OTC_EURUSD"]
        m1 = build_indicators_map_from_po(prov, symbols)
        m2 = build_indicators_map_from_po(prov, symbols)
        assert m1 is not m2
        assert m1["OTC_EURUSD"] is not m2["OTC_EURUSD"]
