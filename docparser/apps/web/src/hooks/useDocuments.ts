import { useQuery } from '@tanstack/react-query';
import api from '@/lib/api';
import type { DocumentFilters, DocumentListItem, PaginatedResponse } from '@/types';

export function useDocuments(filters: DocumentFilters = {}) {
  return useQuery<PaginatedResponse<DocumentListItem>>({
    queryKey: ['documents', filters],
    queryFn:  async () => {
      const params = new URLSearchParams();
      if (filters.status) params.set('status', filters.status);
      if (filters.type)   params.set('type',   filters.type);
      if (filters.tcode)  params.set('tcode',  filters.tcode);
      if (filters.search) params.set('search', filters.search);
      params.set('page',  String(filters.page  ?? 1));
      params.set('limit', String(filters.limit ?? 20));

      const resp = await api.get<PaginatedResponse<DocumentListItem>>(
        `/documents?${params.toString()}`,
      );
      return resp.data;
    },
  });
}
