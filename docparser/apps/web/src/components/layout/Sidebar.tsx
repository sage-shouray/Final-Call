import { NavLink, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard, Upload, History, Clock,
  FileText, ClipboardList, FileCheck, Package, Truck,
  Settings, BarChart2, ChevronLeft,
  ShieldCheck, LogOut, Users, IndianRupee,
} from 'lucide-react';
import uviraLogo from '@/assets/uvira-logo.png';
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

// Single easing curve + duration used everywhere in the sidebar so every
// element (width, text fade, padding) animates in lockstep — that's what
// keeps the collapse/expand feeling like one motion instead of a jumble.
const T = 'duration-300 ease-[cubic-bezier(0.4,0,0.2,1)]';

// ─── Label — the part of a row that fades/collapses away, never unmounts ──────
// Keeping it mounted (vs. conditionally rendering) is what makes the text
// fade smoothly in sync with the sidebar width instead of popping in/out.
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
          'group flex items-center rounded-lg py-2 text-sm font-medium transition-all',
          T,
          collapsed ? 'justify-center px-0' : 'px-3',
          item.comingSoon
            ? 'cursor-not-allowed opacity-40'
            : isActive
              ? 'bg-indigo-50 text-indigo-700 shadow-[inset_2px_0_0_#4F46E5] -ml-px pl-[calc(0.75rem+1px)] dark:bg-indigo-950/50 dark:text-indigo-300'
              : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900 dark:text-neutral-400 dark:hover:bg-neutral-800 dark:hover:text-neutral-100',
        )
      }
      aria-disabled={item.comingSoon}
    >
      <item.icon className={cn('shrink-0 text-current transition-all', T, collapsed ? 'h-5 w-5' : 'h-4 w-4')} aria-hidden />
      <Label collapsed={collapsed} className="flex flex-1 items-center gap-2">
        <span className="flex-1 truncate">{item.label}</span>
        {item.comingSoon && (
          <span className="shrink-0 rounded-full bg-slate-100 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-slate-400 dark:bg-neutral-800 dark:text-neutral-500">
            Soon
          </span>
        )}
        {item.count != null && !item.comingSoon && item.count > 0 && (
          <span className="shrink-0 rounded-full bg-indigo-100 px-2 py-0.5 text-[11px] font-semibold text-indigo-700 dark:bg-indigo-900 dark:text-indigo-300 tabular-nums">
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
    admin:    'bg-violet-100 text-violet-700',
    manager:  'bg-indigo-100 text-indigo-700',
    operator: 'bg-sky-100 text-sky-700',
  };
  return (
    <span className={cn('flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold select-none', colors[role] ?? 'bg-slate-100 text-slate-600 dark:bg-neutral-800 dark:text-neutral-400')}>
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
        'relative flex h-screen flex-col overflow-hidden bg-white border-r border-slate-200 transition-[width] will-change-[width] dark:bg-neutral-900 dark:border-neutral-800',
        T,
        sidebarCollapsed ? 'w-[60px]' : 'w-[220px]',
      )}
    >
      {/* ── Logo ─────────────────────────────────────────────────────────── */}
      <div
        className="flex h-[60px] shrink-0 items-center border-b border-slate-100 cursor-pointer dark:border-neutral-800 px-4"
        onClick={() => navigate('/dashboard')}
      >
        {/* Crossfade between the mark and full logo instead of an abrupt swap */}
        <div className="relative flex h-9 w-9 shrink-0 items-center justify-center">
          <div className={cn('absolute inset-0 flex items-center justify-center rounded-xl bg-indigo-600 shadow-sm transition-opacity', T, sidebarCollapsed ? 'opacity-100' : 'opacity-0')}>
            <span className="text-white text-base font-black tracking-tighter leading-none">U</span>
          </div>
        </div>
        <div className={cn('overflow-hidden transition-all', T, sidebarCollapsed ? 'ml-0 max-w-0 opacity-0' : '-ml-9 max-w-[150px] opacity-100')}>
          <img src={uviraLogo} alt="Uvira.ai" className="h-8 w-auto max-w-[150px] object-contain" />
        </div>
      </div>

      {/* ── Navigation ───────────────────────────────────────────────────── */}
      <nav className="flex-1 overflow-y-auto overflow-x-hidden py-4 space-y-5 pl-3 pr-2">
        {sections.map(({ section, items }) => (
          <div key={section}>
            <p className={cn(
              'mb-1.5 overflow-hidden whitespace-nowrap px-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400 transition-all dark:text-neutral-500',
              T,
              sidebarCollapsed ? 'max-h-0 opacity-0' : 'max-h-4 opacity-100',
            )}>
              {section}
            </p>
            <ul className="space-y-0.5">
              {items.map((item) => (
                <li key={item.to}>
                  <SidebarLink item={item} collapsed={sidebarCollapsed} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      {/* ── Admin Panel ──────────────────────────────────────────────────── */}
      {user?.role === 'admin' && (
        <div className={cn('shrink-0 border-t border-slate-100 dark:border-neutral-800 px-2 py-2', sidebarCollapsed && 'flex justify-center')}>
          {sidebarCollapsed ? (
            <Tooltip content="Admin Panel" side="right">
              <button
                onClick={() => navigate('/admin')}
                className="flex h-9 w-9 items-center justify-center rounded-lg text-violet-600 hover:bg-violet-50 dark:text-violet-400 dark:hover:bg-violet-950/40 transition-colors"
              >
                <ShieldCheck className="h-5 w-5" />
              </button>
            </Tooltip>
          ) : (
            <button
              onClick={() => navigate('/admin')}
              className="flex w-full items-center px-3 py-2 rounded-lg text-sm font-medium text-violet-700 hover:bg-violet-50 dark:text-violet-400 dark:hover:bg-violet-950/40 transition-colors"
            >
              <ShieldCheck className="h-4 w-4 shrink-0" />
              <Label collapsed={false}>Admin Panel</Label>
            </button>
          )}
        </div>
      )}

      {/* ── User profile + logout ─────────────────────────────────────────── */}
      <div className={cn(
        'shrink-0 border-t border-slate-100 dark:border-neutral-800 px-2 py-3',
        sidebarCollapsed ? 'flex flex-col items-center gap-2' : 'space-y-1',
      )}>
        {sidebarCollapsed ? (
          <>
            <Tooltip content={`${user?.name ?? 'User'} · ${user?.role ?? ''}`} side="right">
              <span className="cursor-default">
                <Avatar name={user?.name ?? 'U'} role={role} />
              </span>
            </Tooltip>
            <Tooltip content="Logout" side="right">
              <button
                onClick={() => logoutUser().then(() => navigate('/login'))}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-red-50 hover:text-red-600 dark:text-neutral-500 dark:hover:bg-red-950/40 dark:hover:text-red-400 transition-colors"
              >
                <LogOut className="h-4 w-4" />
              </button>
            </Tooltip>
          </>
        ) : (
          <>
            <div className="flex items-center gap-2.5 rounded-lg px-2 py-2 bg-slate-50 dark:bg-neutral-800">
              <Avatar name={user?.name ?? 'U'} role={role} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-slate-800 dark:text-neutral-100">{user?.name ?? '—'}</p>
                <p className="truncate text-[11px] capitalize text-slate-400 dark:text-neutral-500 font-medium">{user?.role ?? '—'}</p>
              </div>
            </div>
            <button
              onClick={() => logoutUser().then(() => navigate('/login'))}
              className="flex w-full items-center px-3 py-2 rounded-lg text-sm font-medium text-slate-500 hover:bg-red-50 hover:text-red-600 dark:text-neutral-400 dark:hover:bg-red-950/40 dark:hover:text-red-400 transition-colors"
            >
              <LogOut className="h-4 w-4 shrink-0" />
              <Label collapsed={false}>Logout</Label>
            </button>
          </>
        )}
      </div>

      {/* ── Collapse toggle ───────────────────────────────────────────────── */}
      <button
        type="button"
        onClick={toggleSidebar}
        aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        className={cn(
          'absolute -right-3 top-[68px] flex h-6 w-6 items-center justify-center rounded-full border border-slate-200 bg-white shadow-sm text-slate-400 hover:text-slate-600 hover:border-slate-300 dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-500 dark:hover:text-neutral-300 dark:hover:border-neutral-600 transition-all z-10',
          T,
        )}
      >
        <ChevronLeft className={cn('h-3 w-3 transition-transform', T, sidebarCollapsed && 'rotate-180')} />
      </button>
    </aside>
  );
}
