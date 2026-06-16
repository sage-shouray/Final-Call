import { useQuery } from '@tanstack/react-query';
import api from '@/lib/api';
import type { DashboardMetrics } from '@/types';

export function useDashboardMetrics() {
  return useQuery<DashboardMetrics>({
    queryKey:       ['dashboard', 'metrics'],
    queryFn:        async () => {
      const resp = await api.get<DashboardMetrics>('/dashboard/metrics');
      return resp.data;
    },
    refetchInterval: 30_000,   // auto-refresh every 30 s
    staleTime:       25_000,
  });
}
