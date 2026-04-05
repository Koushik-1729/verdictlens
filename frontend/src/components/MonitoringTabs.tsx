import { NavLink } from 'react-router-dom';
import clsx from 'clsx';

export default function MonitoringTabs() {
  const tabs = [
    { to: '/monitoring/overview', label: 'Overview', end: true },
    { to: '/monitoring/dashboards', label: 'Dashboards' },
    { to: '/monitoring/alerts', label: 'Alerts' },
  ];

  return (
    <div className="flex items-center border-b border-[rgb(var(--border))] px-6">
      <h1 className="mr-5 text-[15px] font-semibold text-text-primary">Monitoring</h1>
      {tabs.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          end={tab.end}
          className={({ isActive }) =>
            clsx(
              '-mb-px inline-flex items-center border-b-2 px-3 py-3 text-[13px] font-medium transition-colors',
              isActive
                ? 'border-accent text-accent'
                : 'border-transparent text-text-secondary hover:text-text-primary',
            )
          }
        >
          {tab.label}
        </NavLink>
      ))}
    </div>
  );
}
