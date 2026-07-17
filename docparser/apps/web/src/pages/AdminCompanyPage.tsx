import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft, Users, Globe, IndianRupee, FileText,
  Plus, Edit2, Check, X, TestTube2, CheckCircle2, XCircle,
  Save, UserPlus, Trash2, KeyRound, Circle,
} from 'lucide-react';

const PASSWORD_MIN_LENGTH = 8;
import { api } from '@/lib/api';
import { cn } from '@/lib/cn';

// ── Types ────────────────────────────────────────────────────────────────────

interface Company {
  id: string; name: string; slug: string; gstin: string;
  email: string; phone: string; address: string; status: string;
}
interface ApiConfig {
  id: string; api_key: string; label: string; workflow: string;
  base_url: string; path: string; method: string; sap_client: string;
  auth_type: string; username: string; is_active: boolean;
  last_tested_at: string | null; last_test_status: string | null;
  full_url: string;
}
interface Pricing {
  id: string; tcode: string; label: string; price_per_document: number;
}
interface CompanyUser {
  id: string; name: string; email: string; role: string;
  is_active: boolean; last_login: string | null; doc_count: number;
}
interface Document {
  document_id: string; type: string; tcode: string; status: string;
  page_count: number; uploaded_at: string; uploaded_by: string;
}
interface BillingLineItem {
  tcode: string; label: string; doc_count: number; price_each: number; amount: number;
}
interface BillingRecord {
  id: string; period_month: number; period_year: number; tcode: string;
  doc_count: number; price_each: number; total_amount: number; status: string;
}
interface Billing {
  tenant_id: string; period_month: number; period_year: number;
  line_items: BillingLineItem[]; total_due: number; history: BillingRecord[];
}

// ── Fetch helpers ─────────────────────────────────────────────────────────────

const fetchCompany  = (id: string) => api.get(`/admin/companies/${id}`).then(r => r.data as Company);
const fetchApis     = (id: string) => api.get(`/admin/companies/${id}/apis`).then(r => r.data as ApiConfig[]);
const fetchPricing  = (id: string) => api.get(`/admin/companies/${id}/pricing`).then(r => r.data as Pricing[]);
const fetchUsers    = (id: string) => api.get(`/admin/companies/${id}/users`).then(r => r.data as CompanyUser[]);
const fetchDocs     = (id: string) => api.get(`/admin/companies/${id}/documents?limit=50`).then(r => r.data as { documents: Document[]; total: number });
const fetchBilling  = (id: string) => api.get(`/admin/companies/${id}/billing`).then(r => r.data as Billing);

// ── Small helpers ─────────────────────────────────────────────────────────────

const TABS = ['Users', 'APIs', 'Pricing', 'Documents', 'Billing'] as const;
type Tab = typeof TABS[number];

const MONTH_NAMES = ['', 'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

function fmtINR(n: number) {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(n);
}

function TabBtn({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'px-4 py-2.5 text-sm font-medium border-b-2 transition-colors',
        active
          ? 'border-violet-600 text-violet-700 dark:text-violet-400 dark:border-violet-400'
          : 'border-transparent text-neutral-500 hover:text-neutral-700 dark:text-neutral-400 dark:hover:text-neutral-200',
      )}
    >{label}</button>
  );
}

function Badge({ label, green }: { label: string; green: boolean }) {
  return (
    <span className={cn('rounded-full px-2 py-0.5 text-xs font-medium', green
      ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400'
      : 'bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-400'
    )}>{label}</span>
  );
}

// ── Inline edit cell ──────────────────────────────────────────────────────────

function EditableCell({ value, onSave }: { value: string | number; onSave: (v: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(String(value));
  if (!editing) return (
    <span className="flex items-center gap-1 group cursor-pointer" onClick={() => setEditing(true)}>
      {value}
      <Edit2 className="h-3 w-3 opacity-0 group-hover:opacity-50 transition-opacity" />
    </span>
  );
  return (
    <span className="flex items-center gap-1">
      <input
        autoFocus
        value={val}
        onChange={e => setVal(e.target.value)}
        className="w-28 rounded border border-violet-400 px-1.5 py-0.5 text-sm focus:outline-none dark:bg-neutral-800"
        onKeyDown={e => { if (e.key === 'Enter') { onSave(val); setEditing(false); } if (e.key === 'Escape') setEditing(false); }}
      />
      <button onClick={() => { onSave(val); setEditing(false); }} className="text-emerald-600"><Check className="h-3.5 w-3.5" /></button>
      <button onClick={() => setEditing(false)} className="text-red-500"><X className="h-3.5 w-3.5" /></button>
    </span>
  );
}

// ── Users tab ─────────────────────────────────────────────────────────────────

function UsersTab({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();
  const { data: users = [], isLoading } = useQuery({ queryKey: ['admin-users', tenantId], queryFn: () => fetchUsers(tenantId) });
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: '', email: '', role: 'operator', password: '' });
  const [formError, setFormError] = useState('');

  const addUser = useMutation({
    mutationFn: (body: typeof form) => api.post(`/admin/companies/${tenantId}/users`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-users', tenantId] });
      setShowForm(false);
      setForm({ name: '', email: '', role: 'operator', password: '' });
      setFormError('');
    },
    onError: (e: any) => setFormError(e?.response?.data?.detail ?? 'Failed to add user.'),
  });

  const toggleUser = useMutation({
    mutationFn: ({ uid, active }: { uid: string; active: boolean }) =>
      api.put(`/admin/companies/${tenantId}/users/${uid}`, { is_active: active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users', tenantId] }),
  });

  const changeRole = useMutation({
    mutationFn: ({ uid, role }: { uid: string; role: string }) =>
      api.put(`/admin/companies/${tenantId}/users/${uid}`, { role }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users', tenantId] }),
  });

  const deleteUser = useMutation({
    mutationFn: (uid: string) => api.delete(`/admin/companies/${tenantId}/users/${uid}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users', tenantId] }),
  });

  const [resetTarget, setResetTarget] = useState<CompanyUser | null>(null);
  const [resetPassword, setResetPassword] = useState('');
  const [resetError, setResetError] = useState('');

  const resetUserPassword = useMutation({
    mutationFn: ({ uid, new_password }: { uid: string; new_password: string }) =>
      api.put(`/admin/companies/${tenantId}/users/${uid}`, { new_password }),
    onSuccess: () => { setResetTarget(null); setResetPassword(''); setResetError(''); },
    onError: (e: any) => setResetError(e?.response?.data?.detail ?? 'Failed to reset password.'),
  });

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button onClick={() => { setShowForm(s => !s); setFormError(''); }}
          className="flex items-center gap-2 rounded-lg bg-violet-600 px-3 py-2 text-sm font-medium text-white hover:bg-violet-700">
          <UserPlus className="h-4 w-4" /> Add User
        </button>
      </div>

      {showForm && (
        <div className="rounded-xl border border-violet-200 bg-violet-50 p-4 dark:border-violet-800 dark:bg-violet-950/30 space-y-3">
          <p className="text-sm font-semibold text-violet-800 dark:text-violet-300">New User</p>
          <div className="grid grid-cols-2 gap-3">
            {(['name', 'email'] as const).map(f => (
              <input key={f} placeholder={f.charAt(0).toUpperCase() + f.slice(1)}
                type="text"
                value={form[f]} onChange={e => setForm(p => ({ ...p, [f]: e.target.value }))}
                className="rounded-lg border border-neutral-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500 dark:border-neutral-700 dark:bg-neutral-800 dark:text-white" />
            ))}
            <div>
              <input placeholder="Password *"
                type="password"
                value={form.password} onChange={e => setForm(p => ({ ...p, password: e.target.value }))}
                className={cn(
                  'w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 dark:bg-neutral-800 dark:text-white',
                  form.password.length === 0
                    ? 'border-neutral-200 focus:ring-violet-500 dark:border-neutral-700'
                    : form.password.length >= PASSWORD_MIN_LENGTH
                      ? 'border-emerald-300 focus:ring-emerald-400 dark:border-emerald-700'
                      : 'border-red-300 focus:ring-red-400 dark:border-red-700',
                )} />
              <p className={cn('mt-1 flex items-center gap-1.5 text-xs',
                form.password.length === 0
                  ? 'text-neutral-400'
                  : form.password.length >= PASSWORD_MIN_LENGTH
                    ? 'text-emerald-600'
                    : 'text-red-500')}>
                {form.password.length >= PASSWORD_MIN_LENGTH
                  ? <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                  : <Circle className="h-3.5 w-3.5 shrink-0" />}
                Password must be at least {PASSWORD_MIN_LENGTH} characters
                <span className="text-red-500">*</span>
              </p>
            </div>
            <select value={form.role} onChange={e => setForm(p => ({ ...p, role: e.target.value }))}
              className="rounded-lg border border-neutral-200 px-3 py-2 text-sm focus:outline-none dark:border-neutral-700 dark:bg-neutral-800 dark:text-white">
              {['operator', 'manager', 'admin'].map(r => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
          {formError && <p className="text-sm text-red-500">{formError}</p>}
          <div className="flex gap-2">
            <button
              onClick={() => addUser.mutate(form)}
              disabled={addUser.isPending || form.password.length < PASSWORD_MIN_LENGTH || !form.name || !form.email}
              className="flex items-center gap-1.5 rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-50 disabled:cursor-not-allowed">
              <Save className="h-3.5 w-3.5" /> {addUser.isPending ? 'Saving…' : 'Save'}
            </button>
            <button onClick={() => { setShowForm(false); setFormError(''); }} className="rounded-lg px-4 py-2 text-sm text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800">Cancel</button>
          </div>
        </div>
      )}

      {isLoading ? <p className="text-sm text-neutral-400 py-8 text-center">Loading…</p> : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-neutral-100 dark:border-neutral-800">
              {['Name', 'Email', 'Role', 'Docs', 'Status', 'Last Login', 'Actions'].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-neutral-400">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
            {users.map(u => (
              <tr key={u.id} className="hover:bg-neutral-50 dark:hover:bg-neutral-800/40">
                <td className="px-4 py-3 font-medium text-neutral-900 dark:text-white">{u.name}</td>
                <td className="px-4 py-3 text-neutral-500">{u.email}</td>
                <td className="px-4 py-3">
                  <select value={u.role}
                    onChange={e => changeRole.mutate({ uid: u.id, role: e.target.value })}
                    className="rounded border border-neutral-200 px-2 py-0.5 text-xs dark:border-neutral-700 dark:bg-neutral-800 dark:text-white">
                    {['operator', 'manager', 'admin'].map(r => <option key={r} value={r}>{r}</option>)}
                  </select>
                </td>
                <td className="px-4 py-3 tabular-nums text-neutral-600 dark:text-neutral-400">{u.doc_count}</td>
                <td className="px-4 py-3"><Badge label={u.is_active ? 'Active' : 'Inactive'} green={u.is_active} /></td>
                <td className="px-4 py-3 text-xs text-neutral-400">{u.last_login ? new Date(u.last_login).toLocaleDateString('en-IN') : '—'}</td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <button onClick={() => toggleUser.mutate({ uid: u.id, active: !u.is_active })}
                      className={cn('text-xs px-2.5 py-1 rounded-lg font-medium transition-colors',
                        u.is_active ? 'bg-red-50 text-red-600 hover:bg-red-100' : 'bg-emerald-50 text-emerald-600 hover:bg-emerald-100')}>
                      {u.is_active ? 'Deactivate' : 'Activate'}
                    </button>
                    <button
                      onClick={() => { setResetTarget(u); setResetPassword(''); setResetError(''); }}
                      className="flex items-center justify-center rounded-lg p-1.5 text-neutral-400 hover:bg-violet-50 hover:text-violet-600 transition-colors"
                      title="Reset password"
                    >
                      <KeyRound className="h-3.5 w-3.5" />
                    </button>
                    <button
                      onClick={() => { if (confirm(`Delete user "${u.name}"? This cannot be undone.`)) deleteUser.mutate(u.id); }}
                      className="flex items-center justify-center rounded-lg p-1.5 text-neutral-400 hover:bg-red-50 hover:text-red-600 transition-colors"
                      title="Delete user"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* Reset password modal */}
      {resetTarget && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 px-4"
          onClick={() => setResetTarget(null)}
        >
          <div
            className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-2xl dark:bg-neutral-900"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-start justify-between">
              <div className="flex h-11 w-11 items-center justify-center rounded-full bg-violet-50 dark:bg-violet-950/40">
                <KeyRound className="h-5 w-5 text-violet-600" />
              </div>
              <button onClick={() => setResetTarget(null)} className="text-neutral-400 hover:text-neutral-600">
                <X className="h-4.5 w-4.5" />
              </button>
            </div>
            <h3 className="mt-4 text-[16px] font-bold text-neutral-900 dark:text-white">Reset password</h3>
            <p className="mt-1 text-[13px] text-neutral-500 dark:text-neutral-400">
              Set a new password for <span className="font-semibold">{resetTarget.name}</span> ({resetTarget.email}).
            </p>
            <input
              type="text"
              autoFocus
              value={resetPassword}
              onChange={e => setResetPassword(e.target.value)}
              placeholder="New password *"
              className={cn(
                'mt-4 w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 dark:bg-neutral-800 dark:text-white',
                resetPassword.length === 0
                  ? 'border-neutral-200 focus:ring-violet-500 dark:border-neutral-700'
                  : resetPassword.length >= PASSWORD_MIN_LENGTH
                    ? 'border-emerald-300 focus:ring-emerald-400 dark:border-emerald-700'
                    : 'border-red-300 focus:ring-red-400 dark:border-red-700',
              )}
            />
            <p className={cn('mt-1.5 flex items-center gap-1.5 text-xs',
              resetPassword.length === 0
                ? 'text-neutral-400'
                : resetPassword.length >= PASSWORD_MIN_LENGTH
                  ? 'text-emerald-600'
                  : 'text-red-500')}>
              {resetPassword.length >= PASSWORD_MIN_LENGTH
                ? <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                : <Circle className="h-3.5 w-3.5 shrink-0" />}
              Password must be at least {PASSWORD_MIN_LENGTH} characters
              <span className="text-red-500">*</span>
            </p>
            {resetError && <p className="mt-2 text-sm text-red-500">{resetError}</p>}
            <div className="mt-4 flex gap-2">
              <button
                onClick={() => resetTarget && resetUserPassword.mutate({ uid: resetTarget.id, new_password: resetPassword })}
                disabled={resetUserPassword.isPending || resetPassword.length < PASSWORD_MIN_LENGTH}
                className="flex-1 rounded-xl bg-violet-600 py-2.5 text-sm font-semibold text-white hover:bg-violet-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {resetUserPassword.isPending ? 'Saving…' : 'Reset Password'}
              </button>
              <button onClick={() => setResetTarget(null)} className="rounded-xl px-4 py-2.5 text-sm text-neutral-500 hover:bg-neutral-100 dark:hover:bg-neutral-800">
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── APIs tab ──────────────────────────────────────────────────────────────────

function ApisTab({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();
  const { data: apis = [], isLoading } = useQuery({ queryKey: ['admin-apis', tenantId], queryFn: () => fetchApis(tenantId) });
  const [testing, setTesting] = useState<string | null>(null);

  const updateApi = useMutation({
    mutationFn: ({ key, body }: { key: string; body: object }) =>
      api.put(`/admin/companies/${tenantId}/apis/${key}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-apis', tenantId] }),
  });

  const testApi = async (apiKey: string) => {
    setTesting(apiKey);
    try { await api.post(`/admin/companies/${tenantId}/apis/${apiKey}/test`); }
    finally { setTesting(null); qc.invalidateQueries({ queryKey: ['admin-apis', tenantId] }); }
  };

  const grouped = apis.reduce<Record<string, ApiConfig[]>>((acc, a) => {
    (acc[a.workflow] ??= []).push(a); return acc;
  }, {});

  if (isLoading) return <p className="text-sm text-neutral-400 py-8 text-center">Loading…</p>;

  return (
    <div className="space-y-6">
      {Object.entries(grouped).map(([workflow, items]) => (
        <div key={workflow}>
          <p className="mb-2 text-xs font-semibold uppercase tracking-widest text-neutral-400">{workflow}</p>
          <div className="rounded-xl border border-neutral-200 overflow-hidden dark:border-neutral-800">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-neutral-50 dark:bg-neutral-800/50 border-b border-neutral-200 dark:border-neutral-800">
                  {['API', 'Method', 'Base URL', 'Path', 'SAP Client', 'Status', 'Actions'].map(h => (
                    <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-neutral-400">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
                {items.map(a => (
                  <tr key={a.api_key} className="hover:bg-neutral-50 dark:hover:bg-neutral-800/30">
                    <td className="px-4 py-3 font-medium text-neutral-900 dark:text-white">{a.label}</td>
                    <td className="px-4 py-3">
                      <span className={cn('rounded px-1.5 py-0.5 text-xs font-mono font-bold',
                        a.method === 'GET' ? 'bg-blue-100 text-blue-700' : 'bg-orange-100 text-orange-700')}>
                        {a.method}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs">
                      <EditableCell value={a.base_url || '—'} onSave={v => updateApi.mutate({ key: a.api_key, body: { base_url: v } })} />
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-neutral-500">{a.path}</td>
                    <td className="px-4 py-3 text-xs">
                      <EditableCell value={a.sap_client} onSave={v => updateApi.mutate({ key: a.api_key, body: { sap_client: v } })} />
                    </td>
                    <td className="px-4 py-3">
                      {a.last_test_status === 'ok'
                        ? <span className="flex items-center gap-1 text-xs text-emerald-600"><CheckCircle2 className="h-3.5 w-3.5" /> OK</span>
                        : a.last_test_status === 'failed'
                          ? <span className="flex items-center gap-1 text-xs text-red-500"><XCircle className="h-3.5 w-3.5" /> Failed</span>
                          : <span className="text-xs text-neutral-400">Not tested</span>}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => testApi(a.api_key)}
                        disabled={testing === a.api_key}
                        className="flex items-center gap-1 rounded-lg bg-neutral-100 px-2.5 py-1 text-xs font-medium text-neutral-700 hover:bg-neutral-200 disabled:opacity-50 transition-colors dark:bg-neutral-800 dark:text-neutral-300 dark:hover:bg-neutral-700"
                      >
                        <TestTube2 className="h-3.5 w-3.5" />
                        {testing === a.api_key ? 'Testing…' : 'Test'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Pricing tab ───────────────────────────────────────────────────────────────

function PricingTab({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();
  const { data: pricing = [], isLoading } = useQuery({ queryKey: ['admin-pricing', tenantId], queryFn: () => fetchPricing(tenantId) });

  const updatePrice = useMutation({
    mutationFn: ({ tcode, price }: { tcode: string; price: number }) =>
      api.put(`/admin/companies/${tenantId}/pricing/${tcode}`, { price_per_document: price }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-pricing', tenantId] }),
  });

  const total = pricing.reduce((s, p) => s + p.price_per_document, 0);

  if (isLoading) return <p className="text-sm text-neutral-400 py-8 text-center">Loading…</p>;

  return (
    <div className="max-w-2xl space-y-4">
      <p className="text-sm text-neutral-500 dark:text-neutral-400">
        Set the price per document processed for each workflow. Click a price to edit it inline.
      </p>
      <div className="rounded-xl border border-neutral-200 overflow-hidden dark:border-neutral-800">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-neutral-50 dark:bg-neutral-800/50 border-b border-neutral-200 dark:border-neutral-800">
              {['Workflow / TCode', 'Price per Document (₹)', ''].map(h => (
                <th key={h} className="px-5 py-3 text-left text-xs font-semibold text-neutral-400">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
            {pricing.map(p => (
              <tr key={p.tcode} className="hover:bg-neutral-50 dark:hover:bg-neutral-800/30">
                <td className="px-5 py-3">
                  <p className="font-medium text-neutral-800 dark:text-white">{p.label}</p>
                  <p className="text-xs text-neutral-400 font-mono">{p.tcode}</p>
                </td>
                <td className="px-5 py-3 font-semibold text-neutral-900 dark:text-white tabular-nums">
                  <EditableCell
                    value={p.price_per_document}
                    onSave={v => updatePrice.mutate({ tcode: p.tcode, price: parseFloat(v) || 0 })}
                  />
                </td>
                <td className="px-5 py-3 text-xs text-neutral-400">per doc</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t-2 border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800/50">
              <td className="px-5 py-3 font-semibold text-neutral-700 dark:text-neutral-300">Average per document</td>
              <td className="px-5 py-3 font-bold text-violet-700 dark:text-violet-400 tabular-nums">
                ₹{(total / (pricing.length || 1)).toFixed(0)}
              </td>
              <td />
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}

// ── Documents tab ─────────────────────────────────────────────────────────────

function DocsTab({ tenantId }: { tenantId: string }) {
  const { data, isLoading } = useQuery({ queryKey: ['admin-docs', tenantId], queryFn: () => fetchDocs(tenantId) });
  const docs = data?.documents ?? [];

  const STATUS_COLOR: Record<string, string> = {
    posted: 'text-emerald-600', validated: 'text-blue-600',
    failed: 'text-red-500', extracted: 'text-amber-600',
    uploaded: 'text-neutral-400',
  };

  if (isLoading) return <p className="text-sm text-neutral-400 py-8 text-center">Loading…</p>;

  return (
    <div>
      <p className="mb-3 text-sm text-neutral-500">Showing last 50 documents · Total: {data?.total ?? 0}</p>
      <div className="rounded-xl border border-neutral-200 overflow-hidden dark:border-neutral-800">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-neutral-50 dark:bg-neutral-800/50 border-b border-neutral-200 dark:border-neutral-800">
              {['Document ID', 'Type', 'TCode', 'Pages', 'Status', 'Date'].map(h => (
                <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-neutral-400">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
            {docs.map(d => (
              <tr key={d.document_id} className="hover:bg-neutral-50 dark:hover:bg-neutral-800/30">
                <td className="px-4 py-3 font-mono text-xs text-neutral-700 dark:text-neutral-300">{d.document_id}</td>
                <td className="px-4 py-3 text-neutral-600 dark:text-neutral-400 capitalize">{d.type.replace('_', ' ')}</td>
                <td className="px-4 py-3"><span className="rounded bg-neutral-100 px-1.5 py-0.5 text-xs font-mono dark:bg-neutral-800">{d.tcode}</span></td>
                <td className="px-4 py-3 tabular-nums text-neutral-500">{d.page_count || '—'}</td>
                <td className={cn('px-4 py-3 font-medium capitalize', STATUS_COLOR[d.status] ?? 'text-neutral-500')}>{d.status}</td>
                <td className="px-4 py-3 text-xs text-neutral-400">{new Date(d.uploaded_at).toLocaleString('en-IN')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Billing tab ───────────────────────────────────────────────────────────────

function BillingTab({ tenantId }: { tenantId: string }) {
  const { data, isLoading } = useQuery({ queryKey: ['admin-billing', tenantId], queryFn: () => fetchBilling(tenantId) });

  if (isLoading) return <p className="text-sm text-neutral-400 py-8 text-center">Loading…</p>;
  if (!data) return null;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <p className="text-sm text-neutral-500 dark:text-neutral-400">
          Live cost for <span className="font-semibold text-neutral-700 dark:text-neutral-300">{MONTH_NAMES[data.period_month]} {data.period_year}</span> — calculated from documents posted this month × configured pricing.
        </p>
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2 text-right dark:border-emerald-900 dark:bg-emerald-950/30">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-emerald-600 dark:text-emerald-400">Due this month</p>
          <p className="text-lg font-bold text-emerald-700 dark:text-emerald-400 tabular-nums">{fmtINR(data.total_due)}</p>
        </div>
      </div>

      {/* Current month line items */}
      <div className="rounded-xl border border-neutral-200 overflow-hidden dark:border-neutral-800">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-neutral-50 dark:bg-neutral-800/50 border-b border-neutral-200 dark:border-neutral-800">
              {['Workflow', 'TCode', 'Documents', 'Price Each', 'Amount'].map(h => (
                <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-neutral-400">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
            {data.line_items.length === 0 ? (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-sm text-neutral-400">No billable documents processed this month yet.</td></tr>
            ) : data.line_items.map(li => (
              <tr key={li.tcode} className="hover:bg-neutral-50 dark:hover:bg-neutral-800/30">
                <td className="px-4 py-3 font-medium text-neutral-800 dark:text-white">{li.label}</td>
                <td className="px-4 py-3"><span className="rounded bg-neutral-100 px-1.5 py-0.5 text-xs font-mono dark:bg-neutral-800">{li.tcode}</span></td>
                <td className="px-4 py-3 tabular-nums text-neutral-600 dark:text-neutral-400">{li.doc_count}</td>
                <td className="px-4 py-3 tabular-nums text-neutral-500">{fmtINR(li.price_each)}</td>
                <td className="px-4 py-3 tabular-nums font-semibold text-neutral-900 dark:text-white">{fmtINR(li.amount)}</td>
              </tr>
            ))}
          </tbody>
          {data.line_items.length > 0 && (
            <tfoot>
              <tr className="border-t-2 border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800/50">
                <td colSpan={4} className="px-4 py-3 font-semibold text-neutral-700 dark:text-neutral-300">Total due</td>
                <td className="px-4 py-3 font-bold text-emerald-700 dark:text-emerald-400 tabular-nums">{fmtINR(data.total_due)}</td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      {/* History */}
      {data.history.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-widest text-neutral-400">Billing History</p>
          <div className="rounded-xl border border-neutral-200 overflow-hidden dark:border-neutral-800">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-neutral-50 dark:bg-neutral-800/50 border-b border-neutral-200 dark:border-neutral-800">
                  {['Period', 'TCode', 'Documents', 'Amount', 'Status'].map(h => (
                    <th key={h} className="px-4 py-2.5 text-left text-xs font-semibold text-neutral-400">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
                {data.history.map(h => (
                  <tr key={h.id} className="hover:bg-neutral-50 dark:hover:bg-neutral-800/30">
                    <td className="px-4 py-3 text-neutral-600 dark:text-neutral-400">{MONTH_NAMES[h.period_month]} {h.period_year}</td>
                    <td className="px-4 py-3"><span className="rounded bg-neutral-100 px-1.5 py-0.5 text-xs font-mono dark:bg-neutral-800">{h.tcode}</span></td>
                    <td className="px-4 py-3 tabular-nums text-neutral-500">{h.doc_count}</td>
                    <td className="px-4 py-3 tabular-nums font-semibold text-neutral-900 dark:text-white">{fmtINR(h.total_amount)}</td>
                    <td className="px-4 py-3">
                      <span className={cn('rounded-full px-2 py-0.5 text-xs font-medium capitalize',
                        h.status === 'paid'
                          ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400'
                          : 'bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-400')}>
                        {h.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function AdminCompanyPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>('Users');
  const qc = useQueryClient();

  const { data: company, isLoading } = useQuery({
    queryKey: ['admin-company', id],
    queryFn: () => fetchCompany(id!),
    enabled: !!id,
  });

  const updateCompany = useMutation({
    mutationFn: (body: object) => api.put(`/admin/companies/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-company', id] }),
  });

  const deleteCompany = useMutation({
    mutationFn: () => api.delete(`/admin/companies/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin-companies'] }); navigate('/admin'); },
  });

  if (isLoading) return <div className="flex items-center justify-center h-64 text-neutral-400">Loading…</div>;
  if (!company) return <div className="flex items-center justify-center h-64 text-red-500">Company not found.</div>;

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-4">
        <button onClick={() => navigate('/admin')}
          className="flex h-9 w-9 items-center justify-center rounded-lg border border-neutral-200 text-neutral-500 hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800 transition-colors">
          <ArrowLeft className="h-4 w-4" />
        </button>
        <div className="flex-1">
          <h1 className="text-xl font-bold text-neutral-900 dark:text-white">
            <EditableCell value={company.name} onSave={v => updateCompany.mutate({ name: v })} />
          </h1>
          <p className="text-sm text-neutral-400">{company.slug} · {company.email || 'No email set'}</p>
        </div>
        {/* Status toggle */}
        <select
          value={company.status}
          onChange={e => updateCompany.mutate({ status: e.target.value })}
          className="rounded-lg border border-neutral-200 px-3 py-1.5 text-sm font-medium dark:border-neutral-700 dark:bg-neutral-800 dark:text-white"
        >
          {['active', 'trial', 'suspended'].map(s => <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>)}
        </select>
        <button
          onClick={() => { if (confirm(`Delete company "${company.name}"? This will permanently remove all its users, documents, pricing, and API configs. This cannot be undone.`)) deleteCompany.mutate(); }}
          className="flex items-center gap-2 rounded-lg border border-red-200 px-3 py-1.5 text-sm font-medium text-red-600 hover:bg-red-50 dark:border-red-900 dark:hover:bg-red-950/40 transition-colors"
        >
          <Trash2 className="h-3.5 w-3.5" />
          Delete Company
        </button>
      </div>

      {/* Company info cards */}
      <div className="grid grid-cols-4 gap-3">
        {([
          { key: 'gstin',   label: 'GSTIN' },
          { key: 'email',   label: 'Email' },
          { key: 'phone',   label: 'Phone' },
          { key: 'address', label: 'Address' },
        ] as const).map(item => (
          <div key={item.key} className="rounded-xl border border-neutral-200 bg-white p-4 dark:border-neutral-800 dark:bg-neutral-900">
            <p className="text-xs font-semibold uppercase tracking-wide text-neutral-400">{item.label}</p>
            <p className="mt-1 text-sm text-neutral-700 dark:text-neutral-300 truncate">
              <EditableCell value={company[item.key] || '—'} onSave={v => updateCompany.mutate({ [item.key]: v })} />
            </p>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div className="rounded-xl border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
        <div className="flex border-b border-neutral-100 dark:border-neutral-800 px-4">
          {TABS.map(t => (
            <TabBtn key={t} label={t} active={tab === t} onClick={() => setTab(t)} />
          ))}
        </div>
        <div className="p-6">
          {tab === 'Users'     && <UsersTab   tenantId={id!} />}
          {tab === 'APIs'      && <ApisTab    tenantId={id!} />}
          {tab === 'Pricing'   && <PricingTab tenantId={id!} />}
          {tab === 'Documents' && <DocsTab    tenantId={id!} />}
          {tab === 'Billing'   && <BillingTab tenantId={id!} />}
        </div>
      </div>
    </div>
  );
}
