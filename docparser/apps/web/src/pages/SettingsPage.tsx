import { useEffect, useState } from 'react';
import { Moon, Sun, Globe, LayoutDashboard, CheckCircle2 } from 'lucide-react';
import { Topbar }   from '@/components/layout/Topbar';
import { Button }   from '@/components/ui/Button';
import { cn }       from '@/lib/cn';

// ─── Types ────────────────────────────────────────────────────────────────────

type Theme       = 'light' | 'dark';
type DateFmt     = 'DD/MM/YYYY' | 'MM/DD/YYYY' | 'YYYY-MM-DD';
type DefaultView = 'dashboard' | 'documents' | 'upload';

interface AppPrefs {
  theme:          Theme;
  dateFormat:     DateFmt;
  defaultView:    DefaultView;
  notifySuccess:  boolean;
  notifyFailure:  boolean;
  notifyExtract:  boolean;
  compactSidebar: boolean;
  language:       string;
}

const STORAGE_KEY = 'uvira-app-prefs';

function loadPrefs(): AppPrefs {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = { ...defaults(), ...JSON.parse(raw) };
      // Migrate any stale 'system' value from the old three-way picker.
      if (parsed.theme !== 'light' && parsed.theme !== 'dark') parsed.theme = 'light';
      return parsed;
    }
  } catch { /* ignore */ }
  return defaults();
}

function defaults(): AppPrefs {
  return {
    theme:          'light',
    dateFormat:     'DD/MM/YYYY',
    defaultView:    'dashboard',
    notifySuccess:  true,
    notifyFailure:  true,
    notifyExtract:  false,
    compactSidebar: false,
    language:       'en',
  };
}

// ─── Small UI helpers ─────────────────────────────────────────────────────────

function SectionCard({ title, description, children }: {
  title: string; description?: string; children: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-neutral-200 bg-white dark:border-neutral-700 dark:bg-neutral-800">
      <div className="border-b border-neutral-100 px-6 py-4 dark:border-neutral-700">
        <p className="text-sm font-semibold text-neutral-800 dark:text-neutral-200">{title}</p>
        {description && <p className="mt-0.5 text-xs text-neutral-400 dark:text-neutral-500">{description}</p>}
      </div>
      <div className="px-6 py-5 space-y-5">{children}</div>
    </div>
  );
}

function Toggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!on)}
      className={cn(
        'relative inline-flex h-5 w-9 shrink-0 rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none',
        on ? 'bg-indigo-500' : 'bg-neutral-200 dark:bg-neutral-700',
      )}
    >
      <span className={cn(
        'pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow ring-0 transition-transform duration-200',
        on ? 'translate-x-4' : 'translate-x-0',
      )} />
    </button>
  );
}

function SettingRow({ label, description, children }: {
  label: string; description?: string; children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div>
        <p className="text-sm font-medium text-neutral-800 dark:text-neutral-200">{label}</p>
        {description && <p className="mt-0.5 text-xs text-neutral-400 dark:text-neutral-500">{description}</p>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

// ─── Theme picker ─────────────────────────────────────────────────────────────

const THEMES: { id: Theme; label: string; icon: React.ElementType }[] = [
  { id: 'light', label: 'Light', icon: Sun  },
  { id: 'dark',  label: 'Dark',  icon: Moon },
];

function ThemePicker({ value, onChange }: { value: Theme; onChange: (v: Theme) => void }) {
  return (
    <div className="flex gap-2">
      {THEMES.map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          onClick={() => onChange(id)}
          className={cn(
            'flex flex-col items-center gap-1.5 rounded-xl border-2 px-5 py-3 text-xs font-medium transition-all',
            value === id
              ? 'border-indigo-500 bg-indigo-50 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300'
              : 'border-neutral-200 bg-white text-neutral-500 hover:border-indigo-200 hover:bg-indigo-50/30 dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-400 dark:hover:border-indigo-700',
          )}
        >
          <Icon className="h-5 w-5" />
          {label}
        </button>
      ))}
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const [prefs,  setPrefs]  = useState<AppPrefs>(loadPrefs);
  const [saved,  setSaved]  = useState(false);

  useEffect(() => {
    document.title = 'Settings · Uvira.ai';
    return () => { document.title = 'Uvira.ai'; };
  }, []);

  function set<K extends keyof AppPrefs>(key: K, val: AppPrefs[K]) {
    setPrefs(p => ({ ...p, [key]: val }));
  }

  function applyTheme(theme: Theme) {
    document.documentElement.classList.toggle('dark', theme === 'dark');
  }

  function setTheme(theme: Theme) {
    set('theme', theme);
    // Apply immediately so the picker feels responsive, independent of Save.
    applyTheme(theme);
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...prefs, theme }));
  }

  function save() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
    applyTheme(prefs.theme);
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  }

  function reset() {
    const d = defaults();
    setPrefs(d);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(d));
    applyTheme(d.theme);
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <Topbar title="Settings" />

      <div className="flex-1 overflow-y-auto p-6">
        <div className="mx-auto max-w-2xl space-y-5">

          {/* Appearance */}
          <SectionCard
            title="Appearance"
            description="Choose how Uvira.ai looks on your device."
          >
            <ThemePicker value={prefs.theme} onChange={setTheme} />

            <SettingRow
              label="Compact Sidebar"
              description="Start with the sidebar collapsed to give more space to the main content."
            >
              <Toggle on={prefs.compactSidebar} onChange={v => set('compactSidebar', v)} />
            </SettingRow>
          </SectionCard>

          {/* Locale & Display */}
          <SectionCard
            title="Locale & Display"
            description="Control how dates and language appear across the platform."
          >
            <SettingRow label="Language">
              <select
                value={prefs.language}
                onChange={e => set('language', e.target.value)}
                className="rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-1.5 text-sm text-neutral-800 outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-200 dark:focus:ring-indigo-900"
              >
                <option value="en">English</option>
                <option value="hi">Hindi</option>
              </select>
            </SettingRow>

            <SettingRow label="Date Format" description="Used across documents, timestamps, and exports.">
              <select
                value={prefs.dateFormat}
                onChange={e => set('dateFormat', e.target.value as DateFmt)}
                className="rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-1.5 text-sm text-neutral-800 outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-200 dark:focus:ring-indigo-900"
              >
                <option value="DD/MM/YYYY">DD/MM/YYYY</option>
                <option value="MM/DD/YYYY">MM/DD/YYYY</option>
                <option value="YYYY-MM-DD">YYYY-MM-DD</option>
              </select>
            </SettingRow>
          </SectionCard>

          {/* Default Landing */}
          <SectionCard
            title="Default Landing Page"
            description="Where you land after logging in."
          >
            <div className="grid grid-cols-3 gap-3">
              {([
                { id: 'dashboard',  label: 'Dashboard',  icon: LayoutDashboard },
                { id: 'documents',  label: 'Documents',  icon: Globe           },
                { id: 'upload',     label: 'Upload',     icon: Sun             },
              ] as { id: DefaultView; label: string; icon: React.ElementType }[]).map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  onClick={() => set('defaultView', id)}
                  className={cn(
                    'flex flex-col items-center gap-2 rounded-xl border-2 px-4 py-3 text-xs font-medium transition-all',
                    prefs.defaultView === id
                      ? 'border-indigo-500 bg-indigo-50 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300'
                      : 'border-neutral-200 bg-white text-neutral-500 hover:border-indigo-200 dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-400 dark:hover:border-indigo-700',
                  )}
                >
                  <Icon className="h-5 w-5" />
                  {label}
                </button>
              ))}
            </div>
          </SectionCard>

          {/* Notifications */}
          <SectionCard
            title="Notifications"
            description="In-app toast alerts shown during document processing."
          >
            <SettingRow
              label="Processing Success"
              description="Show a confirmation when a document posts to SAP successfully."
            >
              <Toggle on={prefs.notifySuccess} onChange={v => set('notifySuccess', v)} />
            </SettingRow>

            <SettingRow
              label="Processing Failure"
              description="Alert when a document fails at any stage."
            >
              <Toggle on={prefs.notifyFailure} onChange={v => set('notifyFailure', v)} />
            </SettingRow>

            <SettingRow
              label="Extraction Complete"
              description="Notify when OCR extraction finishes (before SAP posting)."
            >
              <Toggle on={prefs.notifyExtract} onChange={v => set('notifyExtract', v)} />
            </SettingRow>
          </SectionCard>

          {/* Save bar */}
          <div className="flex items-center justify-between rounded-xl border border-neutral-200 bg-white px-6 py-4 dark:border-neutral-700 dark:bg-neutral-800">
            <button
              onClick={reset}
              className="text-xs text-neutral-400 underline hover:text-neutral-600"
            >
              Reset to defaults
            </button>
            <div className="flex items-center gap-3">
              {saved && (
                <span className="flex items-center gap-1 text-xs text-green-600">
                  <CheckCircle2 className="h-3.5 w-3.5" /> Preferences saved
                </span>
              )}
              <Button size="sm" onClick={save}>Save Settings</Button>
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}
