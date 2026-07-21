import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

export interface Notification {
  id:        string;
  type:      'success' | 'error' | 'warning' | 'info';
  title:     string;
  message?:  string;
  createdAt: number;
}

interface UIState {
  sidebarCollapsed:    boolean;
  activeNotifications: Notification[];
}

interface UIActions {
  toggleSidebar:       () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  addNotification:     (n: Omit<Notification, 'id' | 'createdAt'>) => void;
  removeNotification:  (id: string) => void;
  clearNotifications:  () => void;
}

export const useUIStore = create<UIState & UIActions>()(
  persist(
    (set) => ({
      // ── State ──────────────────────────────────────────────────────────────
      // Resting state is the slim icon rail; hovering over it temporarily
      // expands it (see Sidebar.tsx) without needing a manual toggle.
      sidebarCollapsed:    true,
      activeNotifications: [],

      // ── Actions ────────────────────────────────────────────────────────────
      toggleSidebar: () =>
        set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),

      setSidebarCollapsed: (collapsed) =>
        set({ sidebarCollapsed: collapsed }),

      addNotification: (n) =>
        set((s) => ({
          activeNotifications: [
            { ...n, id: crypto.randomUUID(), createdAt: Date.now() },
            ...s.activeNotifications,
          ].slice(0, 10), // cap at 10
        })),

      removeNotification: (id) =>
        set((s) => ({
          activeNotifications: s.activeNotifications.filter((n) => n.id !== id),
        })),

      clearNotifications: () =>
        set({ activeNotifications: [] }),
    }),
    {
      name:    'docparser-ui',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        sidebarCollapsed: state.sidebarCollapsed,
      }),
      // v1: sidebar now defaults to the collapsed icon rail (hover to expand)
      // instead of always-expanded — force that new default onto any browser
      // that already persisted the old `sidebarCollapsed: false`.
      version: 1,
      migrate: () => ({ sidebarCollapsed: true }),
    },
  ),
);
