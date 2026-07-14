import type React from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import {
  LayoutDashboard, BarChart2,
  Activity, ArrowLeft, ShieldCheck, LogOut,
} from 'lucide-react';
import { cn } from '@/lib/cn';
import { logoutUser } from '@/store/authStore';

const NAV: { label: string; to: string; icon: React.ElementType; end: boolean }[] = [
  { label: 'Overview / Companies', to: '/admin',           icon: LayoutDashboard, end: true },
  { label: 'Billing',              to: '/admin/billing',   icon: BarChart2,       end: false },
  { label: 'Activity',             to: '/admin/activity',  icon: Activity,        end: false },
];

export function AdminLayout() {
  const navigate = useNavigate();

  return (
    <div className="flex h-screen overflow-hidden bg-neutral-50 dark:bg-neutral-950">
      {/* Sidebar */}
      <aside className="w-56 shrink-0 flex flex-col border-r border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
        {/* Header */}
        <div className="flex h-14 items-center gap-2.5 border-b border-neutral-100 px-4 dark:border-neutral-800">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-gradient-to-br from-violet-600 to-indigo-600">
            <ShieldCheck className="h-4 w-4 text-white" />
          </div>
          <div className="leading-none">
            <p className="text-sm font-bold tracking-tight text-violet-700 dark:text-violet-400">Super Admin</p>
            <p className="text-[10px] text-neutral-400 mt-0.5">Uvira.ai Control Panel</p>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-2 py-4 space-y-0.5">
          {NAV.map(item => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => cn(
                'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                isActive
                  ? 'bg-violet-50 text-violet-700 dark:bg-violet-950 dark:text-violet-300'
                  : 'text-neutral-600 hover:bg-neutral-100 hover:text-neutral-900 dark:text-neutral-400 dark:hover:bg-neutral-800 dark:hover:text-neutral-100',
              )}
            >
              <item.icon className="h-4 w-4 shrink-0" />
              {item.label}
            </NavLink>
          ))}
        </nav>

        {/* Back to app + Logout */}
        <div className="border-t border-neutral-100 px-2 py-2 dark:border-neutral-800 space-y-0.5">
          <button
            onClick={() => navigate('/dashboard')}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-neutral-500 hover:bg-neutral-100 hover:text-neutral-900 transition-colors dark:text-neutral-400 dark:hover:bg-neutral-800 dark:hover:text-neutral-100"
          >
            <ArrowLeft className="h-4 w-4 shrink-0" />
            Back to App
          </button>
          <button
            onClick={() => logoutUser().then(() => navigate('/login'))}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-neutral-500 hover:bg-red-50 hover:text-red-600 transition-colors dark:text-neutral-400 dark:hover:bg-red-950 dark:hover:text-red-400"
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
