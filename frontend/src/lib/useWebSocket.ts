import { useCallback, useEffect, useRef, useState } from 'react';
import type { TraceSummary } from './api';
import { getStoredApiKey } from './api';

const WS_BASE = import.meta.env.VITE_WS_URL ?? `ws://${window.location.host}/ws`;

function buildWsUrl(): string {
  const base = `${WS_BASE}/live`;
  const key = getStoredApiKey();
  return key ? `${base}?key=${encodeURIComponent(key)}` : base;
}

export function useLiveTraces(maxItems = 200) {
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>();

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    try {
      const ws = new WebSocket(buildWsUrl());
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        reconnectTimer.current = setTimeout(connect, 2000);
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (event) => {
        try {
          const trace = JSON.parse(event.data) as TraceSummary;
          setTraces((prev) => [trace, ...prev].slice(0, maxItems));
        } catch {
          // ignore malformed messages
        }
      };
    } catch {
      reconnectTimer.current = setTimeout(connect, 2000);
    }
  }, [maxItems]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const clear = useCallback(() => setTraces([]), []);

  return { traces, connected, clear };
}
