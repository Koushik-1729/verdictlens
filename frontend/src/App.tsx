import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import MonitoringLayout from './components/MonitoringLayout';
import AuthGate from './components/AuthGate';
import Dashboard from './pages/MonitoringOverview';
import Monitoring from './pages/Monitoring';
import Traces from './pages/Traces';
import TraceDetail from './pages/TraceDetail';
import LiveFeed from './pages/LiveFeed';
import Blame from './pages/Blame';
import ReplayPage from './pages/ReplayPage';
import CostExplorer from './pages/CostExplorer';
import Datasets from './pages/Datasets';
import Evaluations from './pages/Evaluations';
import Alerts from './pages/Alerts';
import Playground from './pages/Playground';
import PromptHub from './pages/PromptHub';
import WorkspaceSettings from './pages/WorkspaceSettings';
import Settings from './pages/Settings';

export default function App() {
  return (
    <BrowserRouter>
      <AuthGate>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Navigate to="/monitoring/overview" replace />} />
            <Route path="/monitoring" element={<MonitoringLayout />}>
              <Route index element={<Navigate to="/monitoring/overview" replace />} />
              <Route path="overview" element={<Dashboard />} />
              <Route path="dashboards" element={<Monitoring />} />
              <Route path="alerts" element={<Alerts />} />
            </Route>
            <Route path="/traces" element={<Traces />} />
            <Route path="/traces/:id" element={<TraceDetail />} />
            <Route path="/live" element={<LiveFeed />} />
            <Route path="/blame" element={<Blame />} />
            <Route path="/replay" element={<ReplayPage />} />
            <Route path="/costs" element={<CostExplorer />} />
            <Route path="/datasets" element={<Datasets />} />
            <Route path="/evaluations" element={<Evaluations />} />
            <Route path="/playground" element={<Playground />} />
            <Route path="/prompt-hub" element={<PromptHub />} />
            <Route path="/alerts" element={<Navigate to="/monitoring/alerts" replace />} />
            <Route path="/workspaces" element={<WorkspaceSettings />} />
            <Route path="/settings" element={<Settings />} />
          </Route>
        </Routes>
      </AuthGate>
    </BrowserRouter>
  );
}
