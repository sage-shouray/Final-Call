import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { UserPlus, Save, X } from 'lucide-react';
import { api } from '@/lib/api';
import { cn } from '@/lib/cn';

interface TeamMember {
  id: string; name: string; email: string; role: string;
  is_active: boolean; last_login: string | null; doc_count: number;
}

async function fetchTeam() {
  const r = await api.get('/auth/team');
  return r.data as TeamMember[];
}

export default function TeamPage() {
  const qc = useQueryClient();
  const { data: members = [], isLoading } = useQuery({ queryKey: ['team'], queryFn: fetchTeam });
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: '', email: '', password: '', role: 'operator' });
  const [formError, setFormError] = useState('');

  const addMember = useMutation({
    mutationFn: (body: typeof form) => api.post('/auth/team', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['team'] });
      setShowForm(false);
      setForm({ name: '', email: '', password: '', role: 'operator' });
      setFormError('');
    },
    onError: (e: any) => setFormError(e?.response?.data?.detail ?? 'Failed to add member.'),
  });

  const toggle = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) =>
      api.put(`/auth/team/${id}`, { is_active: active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['team'] }),
  });

  const active   = members.filter(m => m.is_active);
  const inactive = members.filter(m => !m.is_active);

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-neutral-900 dark:text-white">Team</h1>
          <p className="text-sm text-neutral-500 dark:text-neutral-400 mt-0.5">{active.length} active · {inactive.length} inactive</p>
        </div>
        <button
          onClick={() => { setShowForm(s => !s); setFormError(''); }}
          className="flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white hover:bg-indigo-700 transition-colors"
        >
          <UserPlus className="h-4 w-4" />
          Add Member
        </button>
      </div>

      {/* Add member form */}
      {showForm && (
        <div className="rounded-xl border border-indigo-200 bg-indigo-50 p-5 dark:border-indigo-800 dark:bg-indigo-950/30 space-y-4">
          <p className="text-sm font-semibold text-indigo-800 dark:text-indigo-300">New Team Member</p>
          <div className="grid grid-cols-2 gap-3">
            <input placeholder="Full name" value={form.name}
              onChange={e => setForm(p => ({ ...p, name: e.target.value }))}
              className="rounded-lg border border-neutral-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:border-neutral-700 dark:bg-neutral-800 dark:text-white" />
            <input placeholder="Email address" type="email" value={form.email}
              onChange={e => setForm(p => ({ ...p, email: e.target.value }))}
              className="rounded-lg border border-neutral-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:border-neutral-700 dark:bg-neutral-800 dark:text-white" />
            <input placeholder="Password (min 8 chars)" type="password" value={form.password}
              onChange={e => setForm(p => ({ ...p, password: e.target.value }))}
              className="rounded-lg border border-neutral-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:border-neutral-700 dark:bg-neutral-800 dark:text-white" />
            <select value={form.role} onChange={e => setForm(p => ({ ...p, role: e.target.value }))}
              className="rounded-lg border border-neutral-200 px-3 py-2 text-sm focus:outline-none dark:border-neutral-700 dark:bg-neutral-800 dark:text-white">
              <option value="operator">Operator</option>
            </select>
          </div>
          {formError && <p className="text-sm text-red-500">{formError}</p>}
          <div className="flex gap-2">
            <button onClick={() => addMember.mutate(form)} disabled={addMember.isPending}
              className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors">
              <Save className="h-3.5 w-3.5" />
              {addMember.isPending ? 'Adding…' : 'Add Member'}
            </button>
            <button onClick={() => setShowForm(false)}
              className="flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800">
              <X className="h-3.5 w-3.5" /> Cancel
            </button>
          </div>
        </div>
      )}

      {/* Members table */}
      <div className="rounded-xl border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
        {isLoading ? (
          <p className="text-center text-sm text-neutral-400 dark:text-neutral-500 py-16">Loading…</p>
        ) : members.length === 0 ? (
          <p className="text-center text-sm text-neutral-400 dark:text-neutral-500 py-16">No team members yet. Add one above.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-neutral-100 dark:border-neutral-800">
                {['Name', 'Email', 'Role', 'Documents', 'Last Login', 'Status', ''].map(h => (
                  <th key={h} className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wide text-neutral-400 dark:text-neutral-500">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
              {members.map(m => (
                <tr key={m.id} className="hover:bg-neutral-50 dark:hover:bg-neutral-800/40">
                  <td className="px-5 py-3 font-medium text-neutral-900 dark:text-white">{m.name}</td>
                  <td className="px-5 py-3 text-neutral-500 dark:text-neutral-400">{m.email}</td>
                  <td className="px-5 py-3">
                    <span className="rounded-full bg-neutral-100 px-2.5 py-0.5 text-xs font-medium capitalize dark:bg-neutral-800 dark:text-neutral-300">
                      {m.role}
                    </span>
                  </td>
                  <td className="px-5 py-3 tabular-nums text-neutral-500 dark:text-neutral-400">{m.doc_count}</td>
                  <td className="px-5 py-3 text-xs text-neutral-400 dark:text-neutral-500">
                    {m.last_login ? new Date(m.last_login).toLocaleString('en-IN') : 'Never'}
                  </td>
                  <td className="px-5 py-3">
                    <span className={cn('rounded-full px-2 py-0.5 text-xs font-medium',
                      m.is_active
                        ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400'
                        : 'bg-red-50 text-red-600 dark:bg-red-950 dark:text-red-400')}>
                      {m.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td className="px-5 py-3">
                    <button
                      onClick={() => toggle.mutate({ id: m.id, active: !m.is_active })}
                      className={cn('text-xs px-3 py-1 rounded-lg font-medium transition-colors',
                        m.is_active
                          ? 'bg-red-50 text-red-600 hover:bg-red-100 dark:bg-red-950 dark:text-red-400'
                          : 'bg-emerald-50 text-emerald-600 hover:bg-emerald-100 dark:bg-emerald-950 dark:text-emerald-400')}>
                      {m.is_active ? 'Deactivate' : 'Activate'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
