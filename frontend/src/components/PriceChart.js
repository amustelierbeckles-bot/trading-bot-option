import { useEffect, useRef } from 'react';
import { createChart, CandlestickSeries, createSeriesMarkers } from 'lightweight-charts';

export default function PriceChart({ data = [], signal = null }) {
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef(null);
  const markersRef = useRef(null);

  // ── 1. Inicialización del gráfico (se ejecuta una sola vez) ──────────────
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: 450,
      layout: {
        background: { color: '#131722' },
        textColor: '#d1d4dc',
      },
      grid: {
        vertLines: { color: '#1e2130' },
        horzLines: { color: '#1e2130' },
      },
      crosshair: {
        mode: 1,
        vertLine: { width: 1, color: '#4a5568', style: 3 },
        horzLine: { width: 1, color: '#4a5568', style: 3 },
      },
      rightPriceScale: {
        borderColor: '#2B2B43',
        scaleMargins: { top: 0.1, bottom: 0.2 },
      },
      timeScale: {
        borderColor: '#2B2B43',
        timeVisible: true,
        secondsVisible: false,
      },
    });

    // v5 API: chart.addSeries(SeriesType, options)
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#26a69a',
      downColor: '#ef5350',
      borderUpColor: '#26a69a',
      borderDownColor: '#ef5350',
      wickUpColor: '#26a69a',
      wickDownColor: '#ef5350',
    });

    chartRef.current = chart;
    seriesRef.current = candleSeries;

    // Responsivo: ajusta el ancho automáticamente con ResizeObserver
    const resizeObserver = new ResizeObserver(() => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
        });
      }
    });
    resizeObserver.observe(chartContainerRef.current);

    // Limpieza: evita fugas de memoria y gráficos duplicados
    return () => {
      resizeObserver.disconnect();
      chart.remove();
    };
  }, []);

  // ── 2. Actualización de velas cuando cambia `data` ───────────────────────
  useEffect(() => {
    if (!seriesRef.current || !data || data.length === 0) return;

    try {
      const formatted = data
        .map(item => ({
          // Normaliza timestamps en ms o en segundos
          time: typeof item.time === 'number'
            ? Math.floor(item.time > 1e10 ? item.time / 1000 : item.time)
            : Math.floor(new Date(item.time).getTime() / 1000),
          open: parseFloat(item.open),
          high: parseFloat(item.high),
          low: parseFloat(item.low),
          close: parseFloat(item.close),
        }))
        .filter(item => item.time > 0 && !isNaN(item.open))
        .sort((a, b) => a.time - b.time);

      seriesRef.current.setData(formatted);
      chartRef.current?.timeScale().fitContent();
    } catch (err) {
      console.error('Error al actualizar datos del gráfico:', err);
    }
  }, [data]);

  // ── 3. Pintado de flecha (marker) cuando cambia `signal` ─────────────────
  useEffect(() => {
    if (!seriesRef.current) return;

    // Limpia el marker anterior antes de pintar uno nuevo
    if (markersRef.current) {
      markersRef.current.setMarkers([]);
      markersRef.current = null;
    }

    if (!signal) return;

    try {
        const timestamp = typeof signal.timestamp === 'number'
        ? Math.floor(signal.timestamp > 1e10 ? signal.timestamp / 1000 : signal.timestamp)
          : Math.floor(new Date(signal.timestamp).getTime() / 1000);

      if (timestamp <= 0) return;

        const isBuy = signal.type === 'CALL' || signal.type === 'BUY';

      // v5 API: createSeriesMarkers(series, markersArray)
      markersRef.current = createSeriesMarkers(seriesRef.current, [
        {
          time: timestamp,
          position: isBuy ? 'belowBar' : 'aboveBar',
          color: isBuy ? '#26a69a' : '#ef5350',
          shape: isBuy ? 'arrowUp' : 'arrowDown',
          text: signal.price
            ? `${signal.type} @ ${parseFloat(signal.price).toFixed(2)}`
            : signal.type,
        },
      ]);
    } catch (err) {
      console.error('Error al agregar marker de señal:', err);
    }
  }, [signal]);

  return (
    <div className="relative w-full rounded-lg overflow-hidden border border-[#2B2B43]">
      {(!data || data.length === 0) && (
        <div className="absolute inset-0 flex items-center justify-center bg-[#131722] z-10">
          <div className="text-center">
            <p className="text-[#d1d4dc] font-mono text-sm">No hay datos disponibles</p>
            <p className="text-[#d1d4dc]/50 text-xs mt-1">
              Selecciona un activo para ver el gráfico
            </p>
          </div>
        </div>
      )}
      <div ref={chartContainerRef} className="w-full" style={{ height: '450px' }} />
    </div>
  );
}
