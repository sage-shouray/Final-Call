import { NavLink, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard, Upload, History, Clock,
  FileText, ClipboardList, FileCheck, Package, Truck,
  Settings, BarChart2, PanelLeftClose, PanelLeftOpen,
  ShieldCheck, LogOut, Users, IndianRupee,
} from 'lucide-react';
import uviraLogo from '@/assets/uvira-logo-transparent.png';
import { useUIStore } from '@/store/uiStore';
import { useAuthStore, logoutUser } from '@/store/authStore';
import { useDashboardMetrics } from '@/hooks/useDashboardMetrics';
import { Tooltip } from '@/components/ui/Tooltip';
import { cn } from '@/lib/cn';

interface NavItem {
  label:       string;
  to:          string;
  icon:        React.ElementType;
  count?:      number | undefined;
  comingSoon?: boolean;
}
interface NavSection { section: string; items: NavItem[]; }

// Kept short and simple — a snappy, single-property width transition is far
// lighter than animating a dozen properties on every element at once.
const T = 'duration-200 ease-out';

// A soft fading hairline instead of a flat solid border — reads much less
// harsh as a section separator than a plain `border-t`/`border-b`.
function FadeLine() {
  return (
    <div className="h-px shrink-0 bg-gradient-to-r from-transparent via-slate-200 to-transparent dark:via-white/10" />
  );
}

// ─── Label — the part of a row that fades/collapses away, never unmounts ──────
function Label({ collapsed, className, children }: { collapsed: boolean; className?: string; children: React.ReactNode }) {
  return (
    <span
      className={cn(
        'overflow-hidden whitespace-nowrap transition-all',
        T,
        collapsed ? 'ml-0 max-w-0 opacity-0' : 'ml-3 max-w-[180px] opacity-100',
        className,
      )}
    >
      {children}
    </span>
  );
}

// ─── Single nav link ──────────────────────────────────────────────────────────
function SidebarLink({ item, collapsed }: { item: NavItem; collapsed: boolean }) {
  const inner = (
    <NavLink
      to={item.comingSoon ? '#' : item.to}
      onClick={(e) => { if (item.comingSoon) e.preventDefault(); }}
      className={({ isActive }) =>
        cn(
          'group flex items-center rounded-lg text-sm transition-colors',
          collapsed ? 'h-9 w-9 justify-center' : 'px-2.5 py-2',
          item.comingSoon
            ? 'cursor-not-allowed opacity-40'
            : isActive
              ? 'bg-indigo-50 text-indigo-600 font-medium dark:bg-indigo-500/10 dark:text-indigo-400'
              : 'font-normal text-slate-500 hover:bg-slate-50 hover:text-slate-700 dark:text-neutral-400 dark:hover:bg-white/[0.04] dark:hover:text-neutral-200',
        )
      }
      aria-disabled={item.comingSoon}
    >
      {/* Fixed-size icon slot — identical box in both states keeps every icon
          on the same vertical column instead of jumping between sizes. */}
      <span className="flex h-5 w-5 shrink-0 items-center justify-center">
        <item.icon className="h-[18px] w-[18px] text-current" strokeWidth={1.75} aria-hidden />
      </span>
      <Label collapsed={collapsed} className="flex flex-1 items-center gap-2">
        <span className="flex-1 truncate">{item.label}</span>
        {item.comingSoon && (
          <span className="shrink-0 rounded-full bg-slate-100 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-slate-400 dark:bg-neutral-800 dark:text-neutral-500">
            Soon
          </span>
        )}
        {item.count != null && !item.comingSoon && item.count > 0 && (
          <span className="shrink-0 rounded-full bg-indigo-100 px-2 py-0.5 text-[11px] font-semibold text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300 tabular-nums">
            {item.count > 99 ? '99+' : item.count}
          </span>
        )}
      </Label>
    </NavLink>
  );

  if (collapsed) {
    return (
      <Tooltip content={item.comingSoon ? `${item.label} — coming soon` : item.label} side="right">
        {inner}
      </Tooltip>
    );
  }
  return inner;
}

// ─── Avatar ───────────────────────────────────────────────────────────────────
function Avatar({ name, role }: { name: string; role: string }) {
  const initials = name.split(' ').slice(0, 2).map((w) => w[0]?.toUpperCase() ?? '').join('');
  const colors: Record<string, string> = {
    admin:    'bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300',
    manager:  'bg-indigo-100 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300',
    operator: 'bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300',
  };
  return (
    <span className={cn('flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold select-none ring-1 ring-black/5 dark:ring-white/10', colors[role] ?? 'bg-slate-100 text-slate-600 dark:bg-neutral-800 dark:text-neutral-400')}>
      {initials}
    </span>
  );
}

// ─── Sidebar ──────────────────────────────────────────────────────────────────
export function Sidebar() {
  const { sidebarCollapsed, toggleSidebar } = useUIStore();
  const user    = useAuthStore((s) => s.user);
  const navigate = useNavigate();
  const { data: metrics } = useDashboardMetrics();

  const collapsed = sidebarCollapsed;
  const role      = user?.role ?? 'operator';
  const isManager = role === 'manager' || role === 'admin';
  const isManagerOnly = role === 'manager'; // admin uses the Admin Panel's own billing view

  const sections: NavSection[] = [
    {
      section: 'Workspace',
      items: [
        ...(isManager ? [{ label: 'Dashboard', to: '/dashboard', icon: LayoutDashboard, count: metrics?.total_processed }] : []),
        { label: 'Upload Document', to: '/upload',    icon: Upload  },
        { label: 'History',         to: '/documents', icon: History },
        ...(isManager ? [{ label: 'Pending Review', to: '/documents?status=validated', icon: Clock, count: metrics?.pending_review }] : []),
      ],
    },
    {
      section: 'Document Types',
      items: [
        { label: 'Vendor Invoice',  to: '/upload?type=vendor_invoice',  icon: FileText      },
        { label: 'Sales Order',     to: '/upload?type=sales_order',     icon: ClipboardList },
        { label: 'Payment Advice',  to: '/upload?type=payment_advice',  icon: FileCheck     },
        { label: 'Goods Receipt',   to: '/upload?type=goods_receipt',   icon: Package       },
        { label: 'Freight Invoice', to: '/upload?type=freight_invoice', icon: Truck         },
      ],
    },
    ...(isManager ? [{
      section: 'System',
      items: [
        { label: 'Team',     to: '/team',     icon: Users    },
        ...(isManagerOnly ? [{ label: 'Billing', to: '/billing', icon: IndianRupee }] : []),
        { label: 'Reports',  to: '/reports',  icon: BarChart2 },
        { label: 'Settings', to: '/settings', icon: Settings  },
      ],
    }] : []),
  ];

  return (
    <aside
      className={cn(
        'relative flex h-screen shrink-0 flex-col overflow-hidden bg-white shadow-[1px_0_0_0_rgba(15,23,42,0.06)] transition-[width] will-change-[width] dark:bg-neutral-900 dark:shadow-[1px_0_0_0_rgba(255,255,255,0.06)]',
        T,
        collapsed ? 'w-[64px]' : 'w-[224px]',
      )}
    >
      {/* ── Logo + open/close toggle ─────────────────────────────────────── */}
      <div className={cn('flex h-[60px] shrink-0 items-center', collapsed ? 'justify-center px-0' : 'justify-between px-3')}>
        <div
          className="flex items-center cursor-pointer overflow-hidden"
          onClick={() => navigate('/dashboard')}
        >
          {collapsed ? (
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-indigo-700 shadow-sm">
              <span className="text-white text-base font-black tracking-tighter leading-none">U</span>
            </div>
          ) : (
            <img src={uviraLogo} alt="Uvira.ai" className="h-7 w-auto max-w-[140px] object-contain ml-1" />
          )}
        </div>

        {!collapsed && (
          <Tooltip content="Collapse sidebar" side="bottom">
            <button
              type="button"
              onClick={toggleSidebar}
              aria-label="Collapse sidebar"
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:text-neutral-500 dark:hover:bg-white/[0.06] dark:hover:text-neutral-300 transition-colors"
            >
              <PanelLeftClose className="h-4 w-4" />
            </button>
          </Tooltip>
        )}
      </div>

      {collapsed && (
        <div className="flex justify-center pb-2">
          <Tooltip content="Expand sidebar" side="right">
            <button
              type="button"
              onClick={toggleSidebar}
              aria-label="Expand sidebar"
              className="flex h-7 w-7 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:text-neutral-500 dark:hover:bg-white/[0.06] dark:hover:text-neutral-300 transition-colors"
            >
              <PanelLeftOpen className="h-4 w-4" />
            </button>
          </Tooltip>
        </div>
      )}

      <div className="px-3">
        <FadeLine />
      </div>

      {/* ── Navigation ───────────────────────────────────────────────────── */}
      <nav className={cn('flex-1 overflow-y-auto overflow-x-hidden py-4 space-y-6', collapsed ? 'px-2' : 'pl-3 pr-2')}>
        {sections.map(({ section, items }) => (
          <div key={section}>
            {!collapsed && (
              <div className="mb-2 flex items-center gap-1.5 px-2">
                <span className="h-1 w-1 shrink-0 rounded-full bg-indigo-300 dark:bg-indigo-600" />
                <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400 dark:text-neutral-500">
                  {section}
                </p>
              </div>
            )}
            <ul className="space-y-0.5">
              {items.map((item) => (
                <li key={item.to} className={collapsed ? 'flex justify-center' : undefined}>
                  <SidebarLink item={item} collapsed={collapsed} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      {/* ── Admin Panel ──────────────────────────────────────────────────── */}
      {user?.role === 'admin' && (
        <>
          <div className="px-3"><FadeLine /></div>
          <div className={cn('shrink-0 px-2 py-2', collapsed && 'flex justify-center')}>
            {collapsed ? (
              <Tooltip content="Admin Panel" side="right">
                <button
                  onClick={() => navigate('/admin')}
                  className="flex h-9 w-9 items-center justify-center rounded-lg text-violet-600 hover:bg-violet-50 dark:text-violet-400 dark:hover:bg-violet-500/10 transition-colors"
                >
                  <ShieldCheck className="h-[18px] w-[18px]" strokeWidth={1.75} />
                </button>
              </Tooltip>
            ) : (
              <button
                onClick={() => navigate('/admin')}
                className="flex w-full items-center px-2.5 py-2 rounded-lg text-sm text-violet-600 hover:bg-violet-50 dark:text-violet-400 dark:hover:bg-violet-500/10 transition-colors"
              >
                <span className="flex h-5 w-5 shrink-0 items-center justify-center">
                  <ShieldCheck className="h-[18px] w-[18px]" strokeWidth={1.75} />
                </span>
                <Label collapsed={false}>Admin Panel</Label>
              </button>
            )}
          </div>
        </>
      )}

      {/* ── User profile + logout ─────────────────────────────────────────── */}
      <div className="px-3"><FadeLine /></div>
      <div className={cn(
        'shrink-0 px-2 py-3',
        collapsed ? 'flex flex-col items-center gap-2' : 'space-y-1',
      )}>
        {collapsed ? (
          <>
            <Tooltip content={`${user?.name ?? 'User'} · ${user?.role ?? ''}`} side="right">
              <span className="cursor-default">
                <Avatar name={user?.name ?? 'U'} role={role} />
              </span>
            </Tooltip>
            <Tooltip content="Logout" side="right">
              <button
                onClick={() => logoutUser().then(() => navigate('/login'))}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-red-50 hover:text-red-600 dark:text-neutral-500 dark:hover:bg-red-500/10 dark:hover:text-red-400 transition-colors"
              >
                <LogOut className="h-[18px] w-[18px]" strokeWidth={1.75} />
              </button>
            </Tooltip>
          </>
        ) : (
          <>
            <div className="flex items-center gap-2.5 rounded-lg px-2 py-2 bg-slate-50 dark:bg-white/[0.03]">
              <Avatar name={user?.name ?? 'U'} role={role} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-slate-800 dark:text-neutral-100">{user?.name ?? '—'}</p>
                <p className="truncate text-[11px] capitalize text-slate-400 dark:text-neutral-500 font-medium">{user?.role ?? '—'}</p>
              </div>
            </div>
            <button
              onClick={() => logoutUser().then(() => navigate('/login'))}
              className="flex w-full items-center px-2.5 py-2 rounded-lg text-sm text-slate-500 hover:bg-red-50 hover:text-red-600 dark:text-neutral-400 dark:hover:bg-red-500/10 dark:hover:text-red-400 transition-colors"
            >
              <span className="flex h-5 w-5 shrink-0 items-center justify-center">
                <LogOut className="h-[18px] w-[18px]" strokeWidth={1.75} />
              </span>
              <Label collapsed={false}>Logout</Label>
            </button>
          </>
        )}
      </div>
    </aside>
  );
}
