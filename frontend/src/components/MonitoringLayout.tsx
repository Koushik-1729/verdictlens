import { Outlet } from 'react-router-dom';
import MonitoringTabs from './MonitoringTabs';

export default function MonitoringLayout() {
  return (
    <div className="flex h-full flex-col">
      <MonitoringTabs />
      <div className="flex-1 overflow-y-auto px-6 py-5">
        <Outlet />
      </div>
    </div>
  );
}
