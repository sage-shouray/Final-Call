import { useQuery } from '@tanstack/react-query';
import api from '@/lib/api';

export interface DocumentGroupItem {
  document_id: string;
  part: number | null;
  of: number | null;
  invoice_no: string;
  vendor_name: string;
  status: string;
  confidence: 'high' | 'low' | null;
  forced_manual_review: boolean;
}

export interface DocumentGroupResponse {
  group_id: string;
  documents: DocumentGroupItem[];
}

/** Every document split out of the same multi-invoice PDF upload. */
export function useDocumentGroup(groupId: string | undefined) {
  return useQuery<DocumentGroupResponse>({
    queryKey: ['document-group', groupId],
    queryFn:  async () => {
      const resp = await api.get<DocumentGroupResponse>(`/documents/group/${groupId}`);
      return resp.data;
    },
    enabled: !!groupId,
  });
}
