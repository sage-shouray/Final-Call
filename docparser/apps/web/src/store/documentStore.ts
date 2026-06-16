import { create } from 'zustand';
import type { Document } from '@/types';

interface DocumentState {
  currentDocument:  Document | null;
  processingStep:   number;
  uploadProgress:   number;  // 0-100
}

interface DocumentActions {
  setDocument:  (doc: Document | null) => void;
  setStep:      (step: number) => void;
  setProgress:  (pct: number) => void;
  reset:        () => void;
}

const initialState: DocumentState = {
  currentDocument: null,
  processingStep:  0,
  uploadProgress:  0,
};

export const useDocumentStore = create<DocumentState & DocumentActions>((set) => ({
  ...initialState,

  setDocument:  (doc)  => set({ currentDocument: doc }),
  setStep:      (step) => set({ processingStep: step }),
  setProgress:  (pct)  => set({ uploadProgress: Math.min(100, Math.max(0, pct)) }),
  reset:        ()     => set(initialState),
}));
