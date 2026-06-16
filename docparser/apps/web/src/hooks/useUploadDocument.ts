import { useMutation, useQueryClient } from '@tanstack/react-query';
import api from '@/lib/api';
import { useDocumentStore } from '@/store/documentStore';

export interface UploadPayload {
  file:  File;
  tcode: string;
}

interface UploadResult {
  document_id: string;
  status:      string;
  message:     string;
}

export function useUploadDocument() {
  const qc          = useQueryClient();
  const setProgress = useDocumentStore((s) => s.setProgress);

  return useMutation<UploadResult, Error, UploadPayload>({
    mutationFn: async ({ file, tcode }) => {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('tcode', tcode);

      const resp = await api.post<UploadResult>('/documents/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: (e) => {
          if (e.total) {
            setProgress(Math.round((e.loaded / e.total) * 100));
          }
        },
      });
      return resp.data;
    },
    onSuccess: () => {
      setProgress(0);
      qc.invalidateQueries({ queryKey: ['documents'] });
      qc.invalidateQueries({ queryKey: ['dashboard', 'metrics'] });
    },
    onError: () => {
      setProgress(0);
    },
  });
}
