import { useEffect, useRef, useState } from 'react';
import { useAuthStore } from '@/store/authStore';
import type { WebSocketEvent } from '@/types';

type WSStatus = 'idle' | 'connecting' | 'connected' | 'disconnected';

export function useDocumentWebSocket(documentId: string | undefined) {
  const [event,  setEvent]  = useState<WebSocketEvent | null>(null);
  const [status, setStatus] = useState<WSStatus>('idle');
  const wsRef               = useRef<WebSocket | null>(null);
  const retryRef            = useRef<ReturnType<typeof setTimeout>>();
  const retryCount          = useRef(0);
  const accessToken         = useAuthStore((s) => s.accessToken);

  useEffect(() => {
    if (!documentId || !accessToken) {
      setStatus('idle');
      return;
    }

    function connect() {
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const url   = `${proto}://${window.location.host}/api/ws/${documentId}?token=${accessToken}`;

      setStatus('connecting');
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setStatus('connected');
        retryCount.current = 0;
      };

      ws.onmessage = (e: MessageEvent) => {
        try {
          const parsed = JSON.parse(e.data as string) as WebSocketEvent;
          if (parsed.event !== 'PING') setEvent(parsed);
        } catch {
          // ignore malformed frames
        }
      };

      ws.onclose = () => {
        setStatus('disconnected');
        const delay = Math.min(1_000 * 2 ** retryCount.current, 30_000);
        retryCount.current += 1;
        retryRef.current = setTimeout(connect, delay);
      };

      ws.onerror = () => ws.close();
    }

    connect();

    return () => {
      clearTimeout(retryRef.current);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [documentId, accessToken]);

  return { event, status };
}
