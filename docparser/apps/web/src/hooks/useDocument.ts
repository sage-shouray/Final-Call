import { useQuery } from '@tanstack/react-query';
import api from '@/lib/api';
import type { Document } from '@/types';

export function useDocument(documentId: string | undefined) {
  return useQuery<Document>({
    queryKey: ['document', documentId],
    queryFn:  async () => {
      const resp = await api.get<Document>(`/documents/${documentId}`);
      return resp.data;
    },
    enabled:           !!documentId,
    refetchInterval:   (query) => {
      const status = query.state.data?.status;
      // Poll every 3 s while a processing step is in progress
      const active = ['extracting', 'validating', 'posting'];
      return status && active.includes(status) ? 3_000 : false;
    },
  });
}
