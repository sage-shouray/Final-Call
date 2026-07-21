import type React from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { LayoutDashboard, BarChart2, Activity, ArrowLeft, ShieldCheck, LogOut } from 'lucide-react';
import uviraLogo from '@/assets/uvira-logo-transparent.png';
import { cn } from '@/lib/cn';
import { logoutUser } from '@/store/authStore';

const NAV: { label: string; to: string; icon: React.ElementType; end: boolean }[] = [
  { label: 'Overview / Companies', to: '/admin',          icon: LayoutDashboard, end: true  },
  { label: 'Billing',              to: '/admin/billing',  icon: BarChart2,       end: false },
  { label: 'Activity',             to: '/admin/activity', icon: Activity,        end: false },
];

export function AdminLayout() {
  const navigate = useNavigate();

  return (
    <div className="flex h-screen overflow-hidden bg-[#F3F4F8] dark:bg-neutral-950">

      {/* Sidebar */}
      <aside className="w-56 shrink-0 flex flex-col bg-white shadow-[1px_0_0_0_rgba(15,23,42,0.06)] dark:bg-neutral-900 dark:shadow-[1px_0_0_0_rgba(255,255,255,0.06)]">

        {/* Logo + badge */}
        <div className="flex h-[60px] items-center justify-between px-4">
          <img src={uviraLogo} alt="Uvira.ai" className="h-7 w-auto max-w-[120px] object-contain" />
          <span className="flex items-center gap-1 rounded-full bg-violet-100 px-2 py-0.5 text-[10px] font-semibold text-violet-700 uppercase tracking-wide dark:bg-violet-950 dark:text-violet-300">
            <ShieldCheck className="h-3 w-3" />
            Admin
          </span>
        </div>

        <div className="px-3">
          <div className="h-px bg-gradient-to-r from-transparent via-slate-200 to-transparent dark:via-white/10" />
        </div>

        {/* Nav */}
        <nav className="flex-1 px-2 py-4 space-y-0.5">
          <p className="mb-2 px-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400 dark:text-neutral-500">Control Panel</p>
          {NAV.map(item => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => cn(
                'relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-violet-50 text-violet-700 dark:bg-violet-500/10 dark:text-violet-300'
                  : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900 dark:text-neutral-400 dark:hover:bg-white/[0.04] dark:hover:text-neutral-100',
              )}
            >
              <item.icon className="h-4 w-4 shrink-0" />
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="px-3">
          <div className="h-px bg-gradient-to-r from-transparent via-slate-200 to-transparent dark:via-white/10" />
        </div>

        {/* Footer actions */}
        <div className="px-2 py-3 space-y-0.5">
          <button
            onClick={() => navigate('/dashboard')}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-500 hover:bg-slate-50 hover:text-slate-800 dark:text-neutral-400 dark:hover:bg-neutral-800 dark:hover:text-neutral-100 transition-colors"
          >
            <ArrowLeft className="h-4 w-4 shrink-0" />
            Back to App
          </button>
          <button
            onClick={() => logoutUser().then(() => navigate('/login'))}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-500 hover:bg-red-50 hover:text-red-600 dark:text-neutral-400 dark:hover:bg-red-950/40 dark:hover:text-red-400 transition-colors"
          >
            <LogOut className="h-4 w-4 shrink-0" />
            Logout
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
