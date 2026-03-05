import { useState, useEffect, useCallback, useRef } from "react";
import axios from "axios";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
const API_KEY = process.env.REACT_APP_API_KEY;
const POLL_INTERVAL = 30000; // 30s
const STORAGE_KEY   = "risk_manager_config";

const DEFAULT_CONFIG = {
  balance:       1000,
  risk_pct:      2.0,
  session_start: new Date().toISOString(),
};

export default function useRiskManager() {
  const [config, setConfig]         = useState(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      return saved ? { ...DEFAULT_CONFIG, ...JSON.parse(saved) } : DEFAULT_CONFIG;
    } catch {
      return DEFAULT_CONFIG;
    }
  });
  const [riskStatus, setRiskStatus] = useState(null);
  const [loading, setLoading]       = useState(false);
  const cooldownTimerRef            = useRef(null);
  const [cooldownLeft, setCooldownLeft] = useState(0); // segundos restantes

  const fetchRiskStatus = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await axios.post(`${API}/risk/status`, {
        balance:       config.balance,
        risk_pct:      config.risk_pct,
        session_start: config.session_start,
      }, {
        headers: API_KEY ? { "X-API-Key": API_KEY } : {}
      });
      setRiskStatus(data);

      // Si circuit breaker se activa, inicia countdown de 60 minutos
      if (data.circuit_breaker?.triggered && cooldownLeft === 0) {
        setCooldownLeft(data.circuit_breaker.cooldown_minutes * 60);
      }
    } catch (e) {
      console.error("Risk status error:", e);
    } finally {
      setLoading(false);
    }
  }, [config, cooldownLeft]);

  // ── Countdown del circuit breaker ─────────────────────────────────────────
  useEffect(() => {
    if (cooldownLeft <= 0) return;
    cooldownTimerRef.current = setInterval(() => {
      setCooldownLeft(prev => {
        if (prev <= 1) {
          clearInterval(cooldownTimerRef.current);
          // Al expirar, refresca el estado de riesgo
          fetchRiskStatus();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(cooldownTimerRef.current);
  }, [cooldownLeft, fetchRiskStatus]);

  // ── Polling automático ─────────────────────────────────────────────────────
  useEffect(() => {
    fetchRiskStatus();
    const interval = setInterval(fetchRiskStatus, POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [fetchRiskStatus]);

  // ── Persiste config en localStorage ───────────────────────────────────────
  const updateConfig = useCallback((updates) => {
    setConfig(prev => {
      const next = { ...prev, ...updates };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  // ── Nueva sesión ───────────────────────────────────────────────────────────
  const startNewSession = useCallback(() => {
    const newStart = new Date().toISOString();
    updateConfig({ session_start: newStart });
    setCooldownLeft(0);
    setTimeout(fetchRiskStatus, 300);
  }, [updateConfig, fetchRiskStatus]);

  // ── Estado derivado para UI ────────────────────────────────────────────────
  const isBlocked = riskStatus?.circuit_breaker?.triggered || cooldownLeft > 0;

  const cooldownFormatted = cooldownLeft > 0
    ? `${Math.floor(cooldownLeft / 60).toString().padStart(2, "0")}:${(cooldownLeft % 60).toString().padStart(2, "0")}`
    : null;

  return {
    config,
    updateConfig,
    riskStatus,
    loading,
    isBlocked,
    cooldownLeft,
    cooldownFormatted,
    startNewSession,
    refresh: fetchRiskStatus,
  };
}
