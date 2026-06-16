import { NavLink, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard, Upload, History, Clock,
  FileText, Landmark, FileCheck, Package, Truck,
  Settings, BarChart2, ChevronLeft, ChevronRight,
  FileSpreadsheet,
} from 'lucide-react';
import { useUIStore } from '@/store/uiStore';
import { useAuthStore } from '@/store/authStore';
import { useDashboardMetrics } from '@/hooks/useDashboardMetrics';
import { Tooltip } from '@/components/ui/Tooltip';
import { cn } from '@/lib/cn';

// ─── Nav item definition ────────────────────────────────────────────────────

interface NavItem {
  label:       string;
  to:          string;
  icon:        React.ElementType;
  count?:      number | undefined;
  comingSoon?: boolean | undefined;
}

interface NavSection {
  section: string;
  items:   NavItem[];
}

// ─── Single nav link ─────────────────────────────────────────────────────────

function SidebarLink({
  item,
  collapsed,
}: {
  item:      NavItem;
  collapsed: boolean;
}) {
  const inner = (
    <NavLink
      to={item.comingSoon ? '#' : item.to}
      onClick={(e) => { if (item.comingSoon) e.preventDefault(); }}
      className={({ isActive }) =>
        cn(
          'group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
          collapsed && 'justify-center px-2',
          item.comingSoon
            ? 'cursor-not-allowed opacity-40'
            : isActive
              ? 'bg-indigo-50 text-indigo-700'
              : 'text-neutral-600 hover:bg-neutral-100 hover:text-neutral-900',
        )
      }
      aria-disabled={item.comingSoon}
    >
      <item.icon
        className={cn('h-4 w-4 shrink-0', collapsed ? 'h-5 w-5' : '')}
        aria-hidden
      />

      {!collapsed && (
        <>
          <span className="flex-1 truncate">{item.label}</span>
          {item.comingSoon && (
            <span className="rounded-full bg-neutral-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-neutral-400">
              Soon
            </span>
          )}
          {item.count != null && !item.comingSoon && (
            <span className="rounded-full bg-neutral-100 px-2 py-0.5 text-xs font-semibold text-neutral-500">
              {item.count > 999 ? '999+' : item.count}
            </span>
          )}
        </>
      )}
    </NavLink>
  );

  if (collapsed && item.comingSoon) {
    return (
      <Tooltip content={`${item.label} — coming soon`} side="right">
        {inner}
      </Tooltip>
    );
  }
  if (collapsed) {
    return (
      <Tooltip content={item.label} side="right">
        {inner}
      </Tooltip>
    );
  }
  return inner;
}

// ─── Avatar initials ──────────────────────────────────────────────────────────

function Avatar({ name }: { name: string }) {
  const initials = name
    .split(' ')
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? '')
    .join('');
  return (
    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-xs font-bold text-indigo-700 select-none">
      {initials}
    </span>
  );
}

// ─── Sidebar ─────────────────────────────────────────────────────────────────

export function Sidebar() {
  const { sidebarCollapsed, toggleSidebar } = useUIStore();
  const user = useAuthStore((s) => s.user);
  const navigate = useNavigate();

  const { data: metrics } = useDashboardMetrics();

  const sections: NavSection[] = [
    {
      section: 'Workspace',
      items: [
        {
          label: 'Dashboard',
          to:    '/dashboard',
          icon:  LayoutDashboard,
          count: metrics?.total_processed,
        },
        { label: 'Upload Document', to: '/upload',    icon: Upload },
        { label: 'History',         to: '/documents', icon: History },
        {
          label: 'Pending Review',
          to:    '/documents?status=validated',
          icon:  Clock,
          count: metrics?.pending_review,
        },
      ],
    },
    {
      section: 'Document Types',
      items: [
        { label: 'Vendor Invoice',   to: '/upload?type=vendor_invoice',   icon: FileText },
        { label: 'Bank Statement',   to: '/upload?type=bank_statement',   icon: Landmark,     comingSoon: true },
        { label: 'Payment Advice',   to: '/upload?type=payment_advice',   icon: FileCheck,    comingSoon: true },
        { label: 'Goods Receipt',    to: '/upload?type=goods_receipt',    icon: Package,      comingSoon: true },
        { label: 'Freight Invoice',  to: '/upload?type=freight_invoice',  icon: Truck,        comingSoon: true },
      ],
    },
    {
      section: 'System',
      items: [
        { label: 'Reports',  to: '/reports',  icon: BarChart2,       comingSoon: true },
        { label: 'Settings', to: '/settings', icon: Settings,        comingSoon: true },
      ],
    },
  ];

  const w = sidebarCollapsed ? 'w-16' : 'w-60';

  return (
    <aside
      className={cn(
        'relative flex h-screen flex-col border-r border-neutral-200 bg-white transition-all duration-200',
        w,
      )}
    >
      {/* Logo */}
      <div
        className={cn(
          'flex h-14 shrink-0 items-center border-b border-neutral-100 px-4',
          sidebarCollapsed && 'justify-center px-0',
        )}
      >
        <div
          className="flex cursor-pointer items-center gap-2.5"
          onClick={() => navigate('/dashboard')}
        >
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-neutral-900">
            <FileSpreadsheet className="h-4 w-4 text-white" />
          </div>
          {!sidebarCollapsed && (
            <div className="leading-none">
              <p className="text-sm font-bold text-neutral-900 tracking-tight">DocParser</p>
              <p className="text-[10px] text-neutral-400 mt-0.5">SAP Integration Suite</p>
            </div>
          )}
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-2 py-3 space-y-5">
        {sections.map(({ section, items }) => (
          <div key={section}>
            {!sidebarCollapsed && (
              <p className="mb-1 px-3 text-[10px] font-semibold uppercase tracking-widest text-neutral-400">
                {section}
              </p>
            )}
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

      {/* User profile */}
      <div className={cn(
        'shrink-0 border-t border-neutral-100 px-3 py-3',
        sidebarCollapsed && 'flex justify-center px-2',
      )}>
        {sidebarCollapsed ? (
          <Tooltip content={user?.name ?? 'User'} side="right">
            <span>
              <Avatar name={user?.name ?? 'U'} />
            </span>
          </Tooltip>
        ) : (
          <div className="flex items-center gap-2.5 rounded-lg px-1 py-1.5">
            <Avatar name={user?.name ?? 'U'} />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-neutral-800">{user?.name ?? '—'}</p>
              <p className="truncate text-xs capitalize text-neutral-400">{user?.role ?? '—'}</p>
            </div>
          </div>
        )}
      </div>

      {/* Collapse toggle */}
      <button
        type="button"
        onClick={toggleSidebar}
        aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        className={cn(
          'absolute -right-3 top-[52px] flex h-6 w-6 items-center justify-center',
          'rounded-full border border-neutral-200 bg-white shadow-soft-sm',
          'text-neutral-400 hover:text-neutral-600 transition-colors z-10',
        )}
      >
        {sidebarCollapsed
          ? <ChevronRight className="h-3 w-3" />
          : <ChevronLeft  className="h-3 w-3" />
        }
      </button>
    </aside>
  );
}
