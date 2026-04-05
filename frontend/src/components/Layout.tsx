import { NavLink, Outlet } from 'react-router-dom';
import {
  BarChart3, Layers, Radio, Target, RotateCcw, DollarSign,
  Database, FlaskConical, Wand2, BookOpen, Building2, Settings,
  ChevronLeft, ChevronRight,
} from 'lucide-react';
import clsx from 'clsx';
import { useEffect, useState } from 'react';
import { fetchMetrics, fetchAlerts } from '../lib/api';
import { useLocalStorage } from '../lib/useLocalStorage';
import { useKeyboardShortcuts } from '../lib/useKeyboardShortcuts';
import KeyboardShortcutsModal from './KeyboardShortcutsModal';

const SIDEBAR_COLLAPSED_KEY = 'vl_sidebar_collapsed';

interface NavItem {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: string | number | null;
  badgeColor?: string;
  end?: boolean;
}

function NavGroup({ items, collapsed }: { items: NavItem[]; collapsed: boolean }) {
  return (
    <div className={clsx('space-y-0.5', collapsed ? 'px-2' : 'px-3')}>
      {items.map(({ to, label, icon: Icon, badge, badgeColor, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          title={collapsed ? label : undefined}
          className={({ isActive }) =>
            clsx(
              'flex items-center gap-2.5 rounded-md transition-all duration-100',
              collapsed
                ? 'h-8 w-8 justify-center'
                : 'h-7 px-2',
              isActive
                ? 'bg-[rgba(124,90,255,0.14)] text-[#c4b5fd]'
                : 'text-text-muted hover:bg-[rgb(var(--surface-700))] hover:text-text-secondary',
            )
          }
        >
          {({ isActive }) => (
            <>
              <Icon className={clsx('h-[15px] w-[15px] shrink-0', isActive ? 'text-[#c4b5fd]' : 'text-text-muted')} />
              {!collapsed && (
                <>
                  <span className={clsx('flex-1 text-[12.5px]', isActive ? 'font-medium' : 'font-normal')}>
                    {label}
                  </span>
                  {badge != null && badge !== '' && (
                    <span className={clsx('rounded px-1.5 py-0.5 text-[10px] font-medium tabular-nums', badgeColor ?? 'bg-[rgb(var(--surface-600))] text-text-muted')}>
                      {badge}
                    </span>
                  )}
                </>
              )}
            </>
          )}
        </NavLink>
      ))}
    </div>
  );
}

export default function Layout() {
  const [traceCount, setTraceCount] = useState<number | null>(null);
  const [alertCount, setAlertCount] = useState(0);
  const [errorCount, setErrorCount] = useState(0);
  const [collapsed, setCollapsed] = useLocalStorage<boolean>(SIDEBAR_COLLAPSED_KEY, false);
  const { helpOpen, setHelpOpen } = useKeyboardShortcuts();

  useEffect(() => {
    fetchMetrics(1)
      .then((m) => {
        setTraceCount(m.total_traces);
        setErrorCount(m.traces_by_status?.error ?? 0);
      })
      .catch(() => {});
    fetchAlerts()
      .then((r) => setAlertCount(r.length))
      .catch(() => {});
  }, []);

  const observe: NavItem[] = [
    { to: '/monitoring', label: 'Monitoring', icon: BarChart3, badge: alertCount > 0 ? alertCount : null, badgeColor: 'bg-danger/15 text-danger' },
    { to: '/traces', label: 'Traces', icon: Layers, badge: traceCount ? traceCount.toLocaleString() : null, badgeColor: 'bg-accent/10 text-accent' },
    { to: '/live', label: 'Live Feed', icon: Radio, badge: 'LIVE', badgeColor: 'bg-success/10 text-success' },
  ];

  const analyze: NavItem[] = [
    { to: '/blame', label: 'Blame', icon: Target, badge: errorCount > 0 ? errorCount : null, badgeColor: 'bg-danger/15 text-danger' },
    { to: '/replay', label: 'Replay', icon: RotateCcw },
    { to: '/costs', label: 'Cost Explorer', icon: DollarSign },
  ];

  const evaluate: NavItem[] = [
    { to: '/datasets', label: 'Datasets', icon: Database },
    { to: '/evaluations', label: 'Evaluations', icon: FlaskConical },
    { to: '/playground', label: 'Playground', icon: Wand2 },
    { to: '/prompt-hub', label: 'Prompt Hub', icon: BookOpen },
  ];

  const system: NavItem[] = [
    { to: '/workspaces', label: 'Workspaces', icon: Building2 },
    { to: '/settings', label: 'Settings', icon: Settings },
  ];

  return (
    <div className="flex h-full overflow-hidden bg-[var(--bg)]">
      {/* ── Sidebar ──────────────────────────────────────────────────── */}
      <aside
        className={clsx(
          'flex flex-col shrink-0 border-r border-[rgb(var(--border))] bg-[rgb(var(--surface-800))]',
          'transition-[width] duration-200 ease-in-out',
          collapsed ? 'w-[52px]' : 'w-[216px]',
        )}
      >
        {/* Logo */}
        <div className={clsx(
          'flex h-[52px] shrink-0 items-center border-b border-[rgb(var(--border))]',
          collapsed ? 'justify-center px-0' : 'gap-2.5 px-4',
        )}>
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg shadow-sm"
               style={{ background: 'linear-gradient(135deg, #7c5aff 0%, #5a8aff 100%)' }}>
            <span className="text-[11px] font-bold text-white tracking-tight">VL</span>
          </div>
          {!collapsed && (
            <div className="min-w-0 flex-1">
              <div className="text-[13px] font-semibold text-text-primary leading-tight truncate">VerdictLens</div>
              <div className="text-[10px] text-text-muted leading-tight truncate">AI Observability</div>
            </div>
          )}
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto py-3 space-y-4">
          <NavGroup items={observe} collapsed={collapsed} />
          <div className="mx-3 border-t border-[rgb(var(--border))]" />
          <NavGroup items={analyze} collapsed={collapsed} />
          <div className="mx-3 border-t border-[rgb(var(--border))]" />
          <NavGroup items={evaluate} collapsed={collapsed} />
          <div className="mx-3 border-t border-[rgb(var(--border))]" />
          <NavGroup items={system} collapsed={collapsed} />
        </nav>

        {/* Collapse toggle */}
        <div className="shrink-0 border-t border-[rgb(var(--border))] p-2">
          <button
            onClick={() => setCollapsed(!collapsed)}
            title={collapsed ? 'Expand' : 'Collapse'}
            className={clsx(
              'flex items-center justify-center rounded-md text-text-faint transition-colors hover:bg-surface-700/50 hover:text-text-muted',
              collapsed ? 'h-8 w-8' : 'h-7 w-full gap-2 px-2',
            )}
          >
            {collapsed ? <ChevronRight className="h-3.5 w-3.5" /> : <><ChevronLeft className="h-3.5 w-3.5" /><span className="text-[11px]">Collapse</span></>}
          </button>
        </div>
      </aside>

      {/* ── Main content ─────────────────────────────────────────────── */}
      <main className="flex-1 min-h-0 overflow-hidden flex flex-col bg-[var(--bg)]">
        <Outlet />
      </main>

      {helpOpen && <KeyboardShortcutsModal onClose={() => setHelpOpen(false)} />}
    </div>
  );
}
