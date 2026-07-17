import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { ArrowLeft, Save } from 'lucide-react';
import { api } from '@/lib/api';

interface CompanyForm {
  name: string; slug: string; gstin: string; email: string;
  phone: string; address: string; status: string;
}

export default function AdminCompanyNewPage() {
  const navigate = useNavigate();
  const [form, setForm] = useState<CompanyForm>({
    name: '', slug: '', gstin: '', email: '', phone: '', address: '', status: 'trial',
  });
  const [error, setError] = useState('');

  const set = (k: keyof CompanyForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setForm(p => ({ ...p, [k]: e.target.value }));

  const create = useMutation({
    mutationFn: (body: CompanyForm) => api.post('/admin/companies', body),
    onSuccess: res => navigate(`/admin/companies/${res.data.id}`),
    onError: (e: any) => setError(e?.response?.data?.detail ?? 'Failed to create company'),
  });

  const autoSlug = (name: string) => name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

  const fields: { label: string; key: keyof CompanyForm; type?: string; required?: boolean }[] = [
    { label: 'Company Name', key: 'name', required: true },
    { label: 'Slug (URL key)', key: 'slug', required: true },
    { label: 'GSTIN', key: 'gstin' },
    { label: 'Contact Email', key: 'email', type: 'email' },
    { label: 'Phone', key: 'phone', type: 'tel' },
  ];

  return (
    <div className="p-6 max-w-2xl mx-auto space-y-6">
      <div className="flex items-center gap-4">
        <button onClick={() => navigate('/admin')}
          className="flex h-9 w-9 items-center justify-center rounded-lg border border-neutral-200 text-neutral-500 hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800">
          <ArrowLeft className="h-4 w-4" />
        </button>
        <h1 className="text-xl font-bold text-neutral-900 dark:text-white">Add New Company</h1>
      </div>

      <div className="rounded-xl border border-neutral-200 bg-white p-6 dark:border-neutral-800 dark:bg-neutral-900 space-y-5">
        {fields.map(f => (
          <div key={f.key}>
            <label className="block text-xs font-semibold uppercase tracking-wide text-neutral-500 dark:text-neutral-400 mb-1.5">
              {f.label} {f.required && <span className="text-red-500">*</span>}
            </label>
            <input
              type={f.type ?? 'text'}
              value={form[f.key]}
              onChange={e => {
                set(f.key)(e);
                if (f.key === 'name' && !form.slug) {
                  setForm(p => ({ ...p, slug: autoSlug(e.target.value) }));
                }
              }}
              className="w-full rounded-lg border border-neutral-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500 dark:border-neutral-700 dark:bg-neutral-800 dark:text-white"
            />
          </div>
        ))}

        <div>
          <label className="block text-xs font-semibold uppercase tracking-wide text-neutral-500 dark:text-neutral-400 mb-1.5">Address</label>
          <textarea
            value={form.address}
            onChange={set('address')}
            rows={3}
            className="w-full rounded-lg border border-neutral-200 px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500 dark:border-neutral-700 dark:bg-neutral-800 dark:text-white resize-none"
          />
        </div>

        <div>
          <label className="block text-xs font-semibold uppercase tracking-wide text-neutral-500 dark:text-neutral-400 mb-1.5">Status</label>
          <select value={form.status} onChange={set('status')}
            className="w-full rounded-lg border border-neutral-200 px-3 py-2.5 text-sm focus:outline-none dark:border-neutral-700 dark:bg-neutral-800 dark:text-white">
            {['trial', 'active', 'suspended'].map(s => <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>)}
          </select>
        </div>

        {error && <p className="text-sm text-red-500">{error}</p>}

        <div className="flex gap-3 pt-2">
          <button
            onClick={() => create.mutate(form)}
            disabled={!form.name || !form.slug || create.isPending}
            className="flex items-center gap-2 rounded-lg bg-violet-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-violet-700 disabled:opacity-50 transition-colors"
          >
            <Save className="h-4 w-4" />
            {create.isPending ? 'Creating…' : 'Create Company'}
          </button>
          <button onClick={() => navigate('/admin')}
            className="rounded-lg px-5 py-2.5 text-sm text-neutral-500 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800">
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
