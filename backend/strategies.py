"""
Estrategias de trading y motor de consenso multi-estrategia.

5 estrategias ortogonales:
  1. RangeBreakoutStrategy     — breakout de rango + ATR (anti-reversión)
  2. CCIAlligatorStrategy      — CCI extremo (reversión + momentum)
  3. RSIBollingerStrategy      — RSI + Bollinger Bands (reversión a la media)
  4. MACDStochasticStrategy    — MACD + Estocástico (momentum)
  5. EMACrossoverStrategy      — cruce de EMAs (tendencia)
"""
import random
from typing import Dict, List, Optional
from data_provider import IndicatorSet


def _conf_from_extreme(value: float, low_bad: float, low_good: float,
                       high_good: float, high_bad: float,
                       min_conf: float = 0.60, max_conf: float = 0.82) -> float:
    """Calcula confianza según qué tan extremo es un valor (RSI, CCI, Stoch)."""
    if value <= low_good:
        ratio = (low_good - value) / max(low_good - low_bad, 1e-9)
    elif value >= high_good:
        ratio = (value - high_good) / max(high_bad - high_good, 1e-9)
    else:
        return 0.0
    return round(min_conf + (max_conf - min_conf) * min(ratio, 1.0), 2)


class TradingStrategy:
    def __init__(self, name: str, weight: float = 1.0):
        self.name = name
        self.weight = weight
        self.enabled = True
        self.min_confidence = 0.60

    def generate_signal(self, ind: Optional[IndicatorSet] = None) -> Optional[Dict]:
        return None


class RangeBreakoutStrategy(TradingStrategy):
    """
    Breakout de rango usando ATR + EMA21 + histograma MACD.

    Filosofía OPUESTA a las estrategias de reversión (RSI/CCI):
    - RSI/CCI: "precio en extremo → va a revertir al centro"
    - Esta:    "precio rompió el rango → va a CONTINUAR en esa dirección"

    Grupo ortogonal: breakout_volatility (el más anticorrelacionado).
    """
    ATR_MULT     = 1.2
    MIN_ATR_PCT  = 0.04

    def __init__(self):
        super().__init__("Range Breakout + ATR", 1.2)

    def generate_signal(self, ind: Optional[IndicatorSet] = None) -> Optional[Dict]:
        if not (ind and ind.is_real):
            return None

        price     = ind.price
        ema21     = ind.ema21
        atr       = ind.atr
        atr_pct   = ind.atr_pct
        macd_hist = ind.macd_hist
        trend     = ind.trend

        if atr_pct < self.MIN_ATR_PCT or atr <= 0:
            return None

        breakout_band = atr * self.ATR_MULT
        above_range   = price > ema21 + breakout_band
        below_range   = price < ema21 - breakout_band

        if above_range and macd_hist > 0 and trend == "bullish":
            excess_atr = (price - (ema21 + breakout_band)) / atr
            conf = round(min(0.58 + excess_atr * 0.08 + abs(macd_hist) * 2, 0.82), 2)
            return {
                "type":       "CALL",
                "confidence": conf,
                "cci":        round(ind.cci, 1),
                "reason":     (f"Breakout alcista | precio {price:.5f} > "
                               f"EMA21+ATR*{self.ATR_MULT} ({ema21 + breakout_band:.5f}) | "
                               f"MACD hist={macd_hist:.5f}"),
            }

        if below_range and macd_hist < 0 and trend == "bearish":
            excess_atr = ((ema21 - breakout_band) - price) / atr
            conf = round(min(0.58 + excess_atr * 0.08 + abs(macd_hist) * 2, 0.82), 2)
            return {
                "type":       "PUT",
                "confidence": conf,
                "cci":        round(ind.cci, 1),
                "reason":     (f"Breakout bajista | precio {price:.5f} < "
                               f"EMA21-ATR*{self.ATR_MULT} ({ema21 - breakout_band:.5f}) | "
                               f"MACD hist={macd_hist:.5f}"),
            }

        return None


class CCIAlligatorStrategy(TradingStrategy):
    """
    CCI extremo — dos modos:
    REVERSIÓN (CCI 100–149): sobrecomprado/sobrevendido girando.
    MOMENTUM EXTREMO (|CCI| ≥ 150): impulso violento alineado con tendencia.
    """
    def __init__(self):
        super().__init__("CCI + Alligator", 1.2)

    def generate_signal(self, ind: Optional[IndicatorSet] = None) -> Optional[Dict]:
        if ind and ind.is_real:
            cci   = ind.cci
            trend = ind.trend

            if cci >= 150 and trend == "bullish":
                conf = round(min(0.62 + abs(cci) / 1000, 0.82), 2)
                return {"type": "CALL", "confidence": conf, "cci": round(cci, 1),
                        "reason": f"CCI momentum extremo ({cci:.1f}) + tendencia alcista → continuación"}
            if cci <= -150 and trend == "bearish":
                conf = round(min(0.62 + abs(cci) / 1000, 0.82), 2)
                return {"type": "PUT",  "confidence": conf, "cci": round(cci, 1),
                        "reason": f"CCI momentum extremo ({cci:.1f}) + tendencia bajista → continuación"}

            if cci > 100 and trend in ("bearish", "neutral"):
                conf = round(min(0.60 + abs(cci) / 800, 0.80), 2)
                return {"type": "PUT",  "confidence": conf, "cci": round(cci, 1),
                        "reason": f"CCI sobrecomprado ({cci:.1f}) → reversión bajista OTC"}
            if cci < -100 and trend in ("bullish", "neutral"):
                conf = round(min(0.60 + abs(cci) / 800, 0.80), 2)
                return {"type": "CALL", "confidence": conf, "cci": round(cci, 1),
                        "reason": f"CCI sobrevendido ({cci:.1f}) → reversión alcista OTC"}
        return None


class RSIBollingerStrategy(TradingStrategy):
    """
    RSI + precio cerca de banda de Bollinger.
    RSI < 35 + precio en BB inferior → CALL
    RSI > 65 + precio en BB superior → PUT
    """
    def __init__(self):
        super().__init__("RSI + Bollinger Bands", 1.1)

    def generate_signal(self, ind: Optional[IndicatorSet] = None) -> Optional[Dict]:
        if ind and ind.is_real:
            rsi      = ind.rsi
            price    = ind.price
            bb_u     = ind.bb_upper
            bb_l     = ind.bb_lower
            bb_range = max(bb_u - bb_l, 1e-9)

            dist_upper = (bb_u - price) / bb_range
            dist_lower = (price - bb_l) / bb_range

            if rsi < 35 and dist_lower < 0.10:
                conf = _conf_from_extreme(rsi, 10, 35, 65, 90)
                return {"type": "CALL", "confidence": conf, "cci": round(ind.cci, 1),
                        "reason": f"RSI {rsi:.1f} + precio en BB inferior real"}
            if rsi > 65 and dist_upper < 0.10:
                conf = _conf_from_extreme(rsi, 10, 35, 65, 90)
                return {"type": "PUT",  "confidence": conf, "cci": round(ind.cci, 1),
                        "reason": f"RSI {rsi:.1f} + precio en BB superior real"}
        return None


class MACDStochasticStrategy(TradingStrategy):
    """
    Estocástico + histograma MACD: zonas de reversión y agotamiento extremo.
    Stoch ≥95 / ≤5: agotamiento con confirmación MACD; 20/80: giro clásico.
    """
    def __init__(self):
        super().__init__("MACD + Stochastic", 1.0)

    def generate_signal(self, ind: Optional[IndicatorSet] = None) -> Optional[Dict]:
        if ind and ind.is_real:
            stoch     = ind.stoch_k
            histogram = getattr(ind, "macd_hist", ind.macd_line)

            if stoch >= 95 and histogram > 0:
                conf = _conf_from_extreme(stoch, 0, 20, 80, 100)
                return {"type": "PUT", "confidence": conf, "cci": round(ind.cci, 1),
                        "reason": f"Stoch {stoch:.1f} agotamiento alcista extremo + MACD hist > 0"}
            if stoch <= 5 and histogram < 0:
                conf = _conf_from_extreme(stoch, 0, 20, 80, 100)
                return {"type": "CALL", "confidence": conf, "cci": round(ind.cci, 1),
                        "reason": f"Stoch {stoch:.1f} agotamiento bajista extremo + MACD hist < 0"}

            if stoch < 20 and histogram > 0:
                conf = _conf_from_extreme(stoch, 0, 20, 80, 100)
                return {"type": "CALL", "confidence": conf, "cci": round(ind.cci, 1),
                        "reason": f"Stoch {stoch:.1f} sobrevendido + MACD histograma alcista"}
            if stoch > 80 and histogram < 0:
                conf = _conf_from_extreme(stoch, 0, 20, 80, 100)
                return {"type": "PUT",  "confidence": conf, "cci": round(ind.cci, 1),
                        "reason": f"Stoch {stoch:.1f} sobrecomprado + MACD histograma bajista"}
        return None


class EMACrossoverStrategy(TradingStrategy):
    """
    Cruce de EMA9 vs EMA21.
    EMA9 > EMA21 + momentum positivo → CALL
    EMA9 < EMA21 + momentum negativo → PUT
    """
    def __init__(self):
        super().__init__("EMA Crossover", 0.9)

    def generate_signal(self, ind: Optional[IndicatorSet] = None) -> Optional[Dict]:
        if ind and ind.is_real:
            ema9  = ind.ema9
            ema21 = ind.ema21
            diff  = (ema9 - ema21) / max(ema21, 1e-9)
            MIN_DIFF = 0.0003
            if diff > MIN_DIFF:
                conf = round(min(0.60 + abs(diff) * 500, 0.72), 2)
                return {"type": "CALL", "confidence": conf, "cci": round(ind.cci, 1),
                        "reason": f"EMA9 ({ema9:.5f}) > EMA21 ({ema21:.5f}) cruce alcista real"}
            if diff < -MIN_DIFF:
                conf = round(min(0.60 + abs(diff) * 500, 0.72), 2)
                return {"type": "PUT",  "confidence": conf, "cci": round(ind.cci, 1),
                        "reason": f"EMA9 ({ema9:.5f}) < EMA21 ({ema21:.5f}) cruce bajista real"}
        return None


class MultiStrategyEnsemble:
    def __init__(self, strategies: List[TradingStrategy]):
        self.strategies = strategies
        self.name = "Multi-Strategy Ensemble"

    def get_pre_alert_signal(self, ind: Optional[IndicatorSet] = None) -> Optional[Dict]:
        """
        Pre-Alerta: detecta confluencia parcial (exactamente 3 de 5 estrategias).
        Se dispara ANTES de que se forme la señal completa.
        """
        signals = []
        for strategy in self.strategies:
            if not strategy.enabled:
                continue
            sig = strategy.generate_signal(ind)
            if sig and sig["confidence"] >= strategy.min_confidence:
                signals.append({"strategy": strategy.name, "weight": strategy.weight, **sig})

        if len(signals) < 2:
            return None

        call_signals = [s for s in signals if s["type"] == "CALL"]
        put_signals  = [s for s in signals if s["type"] == "PUT"]

        if len(call_signals) >= 3 and len(call_signals) > len(put_signals):
            partial   = call_signals[:3]
            direction = "CALL"
        elif len(put_signals) >= 3 and len(put_signals) > len(call_signals):
            partial   = put_signals[:3]
            direction = "PUT"
        else:
            return None

        if len(partial) >= 4 or (direction == "CALL" and len(call_signals) >= 4) \
                              or (direction == "PUT"  and len(put_signals)  >= 4):
            return None

        avg_confidence = sum(s["confidence"] for s in partial) / len(partial)
        avg_cci        = sum(s.get("cci", 0) for s in partial) / len(partial)
        confluence_pct = round(len(partial) / 5 * 100)
        data_source    = "real" if (ind and ind.is_real) else "simulated"

        return {
            "type":             direction,
            "is_pre_alert":     True,
            "confluence_pct":   confluence_pct,
            "strategies_fired": [s["strategy"] for s in partial],
            "strategies_total": len(signals),
            "confidence":       round(avg_confidence, 2),
            "cci":              round(avg_cci, 1),
            "reason":           partial[0]["reason"],
            "data_source":      data_source,
        }

    def get_consensus_signal(self, ind: Optional[IndicatorSet] = None) -> Optional[Dict]:
        """
        Confluencia REAL: requiere mayoría (≥2 estrategias de acuerdo).
        Cada estrategia evalúa indicadores reales de forma independiente.
        """
        signals = []
        for strategy in self.strategies:
            if not strategy.enabled:
                continue
            sig = strategy.generate_signal(ind)
            if sig and sig["confidence"] >= strategy.min_confidence:
                signals.append({"strategy": strategy.name, "weight": strategy.weight, **sig})

        if len(signals) < 2:
            return None

        call_signals = [s for s in signals if s["type"] == "CALL"]
        put_signals  = [s for s in signals if s["type"] == "PUT"]
        total        = len(signals)

        if len(call_signals) > len(put_signals) and len(call_signals) >= 2:
            agreeing = call_signals
        elif len(put_signals) > len(call_signals) and len(put_signals) >= 2:
            agreeing = put_signals
        else:
            return None

        avg_confidence  = sum(s["confidence"] * s["weight"] for s in agreeing) / sum(s["weight"] for s in agreeing)
        avg_cci         = sum(s.get("cci", 0) for s in agreeing) / len(agreeing)
        consensus_score = len(agreeing) / total
        strength        = "very_strong" if len(agreeing) >= 4 else "strong" if len(agreeing) >= 3 else "moderate"
        data_source     = "real" if (ind and ind.is_real) else "simulated"

        return {
            "type":                agreeing[0]["type"],
            "confidence":          round(avg_confidence, 2),
            "cci":                 round(avg_cci, 1),
            "strength":            strength,
            "strategies_agreeing": [s["strategy"] for s in agreeing],
            "reason":              agreeing[0]["reason"],
            "reasons":             [s["reason"] for s in agreeing],
            "consensus_score":     round(consensus_score, 2),
            "n_strategies":        len(agreeing),
            "n_total":             total,
            "data_source":         data_source,
        }
