import toast from 'react-hot-toast';

const BASE: Parameters<typeof toast>[1] = {
  duration: 4_000,
  style: { fontFamily: 'Inter, sans-serif', fontSize: '0.875rem' },
};

export function useToast() {
  return {
    success: (message: string) => toast.success(message, BASE),
    error:   (message: string) => toast.error(message, { ...BASE, duration: 6_000 }),
    info:    (message: string) => toast(message, { ...BASE, icon: 'ℹ️' }),
    warning: (message: string) => toast(message, { ...BASE, icon: '⚠️' }),
    loading: (message: string) => toast.loading(message, BASE),
    dismiss: (id?: string)     => toast.dismiss(id),
  };
}
