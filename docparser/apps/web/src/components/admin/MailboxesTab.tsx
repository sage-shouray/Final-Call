import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Mail, Plus, Trash2, TestTube2, CheckCircle2, XCircle,
  Loader2, ShieldAlert, ShieldCheck, Inbox,
} from 'lucide-react';
import api from '@/lib/api';
import { cn } from '@/lib/cn';

/**
 * Per-tenant invoice mailboxes.
 *
 * Credentials are write-only: they can be set and tested here, never read back.
 * A mailbox also starts disabled — polling something that was never verified
 * fails quietly in a log nobody is watching, so Test Connection comes first.
 */

interface Mailbox {
  id: string;
  provider: string;
  label: string;
  address: string;
  folder: string;
  poll_interval_s: number;
  enabled: boolean;
  configured: boolean;
  sender_allowlist: string[];
  auto_post_enabled: boolean;
  last_polled_at: string | null;
  last_success_at: string | null;
  last_error: string;
  consecutive_failures: number;
  messages_seen: number;
  documents_ingested: number;
}

const PROVIDERS = [
  { value: 'microsoft_graph', label: 'Microsoft 365 (Graph)',
    hint: 'Office 365 no longer accepts a password for IMAP, so this is the route for Outlook.',
    fields: [
      { key: 'tenant_id',     label: 'Directory (tenant) ID', placeholder: '00000000-0000-0000-0000-000000000000' },
      { key: 'client_id',     label: 'Application (client) ID', placeholder: '00000000-0000-0000-0000-000000000000' },
      { key: 'client_secret', label: 'Client secret VALUE', placeholder: 'shown once when created', secret: true },
    ] },
  { value: 'gmail_imap', label: 'Gmail (app password)',
    hint: 'Needs 2-Step Verification on the account, and IMAP enabled in Gmail settings.',
    fields: [
      { key: 'password', label: 'App password (16 characters)', placeholder: 'abcd efgh ijkl mnop', secret: true },
    ] },
  { value: 'imap', label: 'Other IMAP server',
    hint: 'Any standard IMAP host.',
    fields: [
      { key: 'host',     label: 'IMAP host', placeholder: 'imap.yourhost.com' },
      { key: 'port',     label: 'Port', placeholder: '993' },
      { key: 'username', label: 'Username', placeholder: 'invoices@company.com' },
      { key: 'password', label: 'Password', placeholder: '', secret: true },
    ] },
] as const;

const input = 'w-full rounded-lg border border-neutral-200 px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-800 dark:text-white';

function Health({ mb }: { mb: Mailbox }) {
  if (!mb.enabled) {
    return <span className="text-xs text-neutral-400">Disabled</span>;
  }
  if (mb.consecutive_failures > 0) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-red-600 dark:text-red-400">
        <XCircle className="h-3.5 w-3.5" />
        {mb.consecutive_failures} failure{mb.consecutive_failures > 1 ? 's' : ''}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-xs text-green-600 dark:text-green-400">
      <CheckCircle2 className="h-3.5 w-3.5" /> Polling
    </span>
  );
}

export function MailboxesTab({ tenantId }: { tenantId: string }) {
  const qc = useQueryClient();
  const base = `/admin/companies/${tenantId}/mailboxes`;
  const key = ['admin-mailboxes', tenantId];

  const { data: mailboxes = [], isLoading } = useQuery<Mailbox[]>({
    queryKey: key,
    queryFn: async () => (await api.get<Mailbox[]>(base)).data,
  });

  const [adding, setAdding] = useState(false);
  const [provider, setProvider] = useState<string>('microsoft_graph');
  const [address, setAddress] = useState('');
  const [creds, setCreds] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState('');
  const [testResult, setTestResult] = useState<Record<string, { ok: boolean; text: string }>>({});
  const [testing, setTesting] = useState<string | null>(null);

  const spec = PROVIDERS.find(p => p.value === provider)!;
  // Returns void deliberately: callers fire this from onSuccess and finally
  // blocks where an un-awaited promise would be a floating-promise bug.
  const refresh = (): void => { void qc.invalidateQueries({ queryKey: key }); };

  const create = useMutation({
    mutationFn: () => api.post(base, {
      provider, address, label: address,
      credentials: { ...creds, ...(provider === 'gmail_imap' ? { username: address } : {}) },
    }),
    onSuccess: () => {
      setAdding(false); setAddress(''); setCreds({}); setFormError('');
      refresh();
    },
    onError: (e: unknown) => {
      const err = e as { response?: { data?: { error?: { message?: string } } } };
      setFormError(err.response?.data?.error?.message ?? 'Could not save the mailbox.');
    },
  });

  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: object }) => api.put(`${base}/${id}`, body),
    onSuccess: refresh,
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`${base}/${id}`),
    onSuccess: refresh,
  });

  const runTest = async (mb: Mailbox) => {
    setTesting(mb.id);
    try {
      const { data } = await api.post<{ ok: boolean; error?: string; unread?: number; total?: number }>(
        `${base}/${mb.id}/test`, {});
      setTestResult(p => ({ ...p, [mb.id]: {
        ok: data.ok,
        text: data.ok
          ? `Connected — ${data.unread ?? 0} unread of ${data.total ?? 0}`
          : (data.error ?? 'Connection failed'),
      } }));
    } finally {
      setTesting(null); refresh();
    }
  };

  if (isLoading) return <p className="py-8 text-center text-sm text-neutral-400">Loading…</p>;

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <p className="max-w-2xl text-xs text-neutral-500 dark:text-neutral-400">
          Invoices emailed to these mailboxes are picked up, routed and checked automatically.
          The mailbox identifies the company &mdash; a message never says which company it belongs to,
          since anything in the email itself is written by whoever sent it.
        </p>
        <button
          type="button"
          onClick={() => setAdding(v => !v)}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-2 text-xs font-semibold text-white hover:bg-violet-700"
        >
          <Plus className="h-3.5 w-3.5" /> Add mailbox
        </button>
      </div>

      {adding && (
        <div className="space-y-3 rounded-xl border border-violet-200 bg-violet-50/50 p-4 dark:border-violet-900 dark:bg-violet-950/20">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Provider</label>
              <select className={input} value={provider}
                      onChange={e => { setProvider(e.target.value); setCreds({}); }}>
                {PROVIDERS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Mailbox address</label>
              <input className={input} value={address} placeholder="invoices@company.com"
                     onChange={e => setAddress(e.target.value)} />
            </div>
          </div>

          <p className="text-xs text-neutral-500 dark:text-neutral-400">{spec.hint}</p>

          <div className="grid gap-3 sm:grid-cols-2">
            {spec.fields.map(f => (
              <div key={f.key}>
                <label className="mb-1 block text-xs font-medium text-neutral-600 dark:text-neutral-400">{f.label}</label>
                <input
                  className={input}
                  type={'secret' in f && f.secret ? 'password' : 'text'}
                  placeholder={f.placeholder}
                  value={creds[f.key] ?? ''}
                  onChange={e => setCreds(p => ({ ...p, [f.key]: e.target.value }))}
                />
              </div>
            ))}
          </div>

          {formError && <p className="text-xs text-red-600 dark:text-red-400">{formError}</p>}

          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={!address || create.isPending}
              onClick={() => create.mutate()}
              className="rounded-lg bg-violet-600 px-4 py-2 text-xs font-semibold text-white hover:bg-violet-700 disabled:opacity-50"
            >
              {create.isPending ? 'Saving…' : 'Save mailbox'}
            </button>
            <button type="button" onClick={() => { setAdding(false); setFormError(''); }}
                    className="text-xs text-neutral-500 hover:underline">Cancel</button>
            <span className="text-xs text-neutral-400">Saved disabled &mdash; test it, then switch it on.</span>
          </div>
        </div>
      )}

      {mailboxes.length === 0 && !adding && (
        <div className="rounded-xl border border-dashed border-neutral-300 py-10 text-center dark:border-neutral-700">
          <Inbox className="mx-auto mb-2 h-7 w-7 text-neutral-300 dark:text-neutral-600" />
          <p className="text-sm text-neutral-500 dark:text-neutral-400">No mailbox configured yet.</p>
        </div>
      )}

      {mailboxes.map(mb => {
        const result = testResult[mb.id];
        return (
          <div key={mb.id} className="rounded-xl border border-neutral-200 p-4 dark:border-neutral-800">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="flex items-center gap-2 text-sm font-semibold text-neutral-900 dark:text-white">
                  <Mail className="h-4 w-4 text-neutral-400" />
                  {mb.address}
                </p>
                <p className="mt-0.5 text-xs text-neutral-400">
                  {PROVIDERS.find(p => p.value === mb.provider)?.label ?? mb.provider}
                  {' · '}{mb.folder}{' · every '}{mb.poll_interval_s}s
                  {' · '}{mb.documents_ingested} document{mb.documents_ingested === 1 ? '' : 's'}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Health mb={mb} />
                <button type="button" onClick={() => void runTest(mb)} disabled={testing === mb.id}
                        className="inline-flex items-center gap-1 rounded-lg border border-neutral-200 px-2.5 py-1.5 text-xs hover:bg-neutral-50 disabled:opacity-50 dark:border-neutral-700 dark:hover:bg-neutral-800">
                  {testing === mb.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <TestTube2 className="h-3.5 w-3.5" />}
                  Test
                </button>
                <button
                  type="button"
                  onClick={() => update.mutate({ id: mb.id, body: { enabled: !mb.enabled } })}
                  className={cn('rounded-lg px-2.5 py-1.5 text-xs font-medium',
                    mb.enabled
                      ? 'bg-neutral-100 text-neutral-700 hover:bg-neutral-200 dark:bg-neutral-800 dark:text-neutral-300'
                      : 'bg-green-600 text-white hover:bg-green-700')}
                >
                  {mb.enabled ? 'Pause' : 'Enable'}
                </button>
                <button type="button" onClick={() => remove.mutate(mb.id)}
                        className="rounded-lg p-1.5 text-neutral-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/40">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>

            {result && (
              <p className={cn('mt-2 text-xs', result.ok ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400')}>
                {result.text}
              </p>
            )}
            {!result && mb.last_error && (
              <p className="mt-2 text-xs text-red-600 dark:text-red-400">{mb.last_error}</p>
            )}

            {/* Who may trigger an unattended posting. An address given to vendors
                is effectively public, so this is the control that decides whether
                a stranger's PDF can reach SAP without a person seeing it. */}
            <div className="mt-3 rounded-lg bg-neutral-50 p-3 dark:bg-neutral-800/40">
              <label className="mb-1 flex items-center gap-1.5 text-xs font-medium text-neutral-600 dark:text-neutral-400">
                {mb.auto_post_enabled && mb.sender_allowlist.length > 0
                  ? <ShieldCheck className="h-3.5 w-3.5 text-green-600" />
                  : <ShieldAlert className="h-3.5 w-3.5 text-amber-500" />}
                Senders allowed to post without review
              </label>
              <input
                className={input}
                defaultValue={mb.sender_allowlist.join(', ')}
                placeholder="ap@vendor.com, @trustedvendor.com"
                onBlur={e => {
                  const list = e.target.value.split(',').map(s => s.trim()).filter(Boolean);
                  if (list.join(',') !== mb.sender_allowlist.join(',')) {
                    update.mutate({ id: mb.id, body: { sender_allowlist: list } });
                  }
                }}
              />
              <label className="mt-2 flex items-center gap-2 text-xs text-neutral-600 dark:text-neutral-400">
                <input
                  type="checkbox"
                  checked={mb.auto_post_enabled}
                  onChange={e => update.mutate({ id: mb.id, body: { auto_post_enabled: e.target.checked } })}
                />
                Post automatically when every check passes
              </label>
              <p className="mt-1 text-[11px] text-neutral-400">
                Both are required. Mail from anyone not listed still arrives and is routed &mdash;
                it simply waits for a person.
              </p>
            </div>
          </div>
        );
      })}
    </div>
  );
}
