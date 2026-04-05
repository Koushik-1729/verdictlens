import { useEffect, useState } from 'react';
import { Bell, BellOff, Plus, Trash2, X } from 'lucide-react';
import EmptyState from '../components/EmptyState';
import { OutlineButton, PrimaryButton, SectionLabel, StatusDot } from '../components/ui';
import { createAlert, deleteAlert, fetchAlerts, type AlertRule } from '../lib/api';

const METRIC_OPTIONS = [
  { value: 'error_rate', label: 'Error Rate', placeholder: 'e.g. > 0.05 (5%)' },
  { value: 'avg_latency_ms', label: 'Avg Latency (ms)', placeholder: 'e.g. > 5000' },
  { value: 'cost_per_hour', label: 'Cost per Hour ($)', placeholder: 'e.g. > 1.50' },
];

export default function Alerts() {
  const [alerts, setAlerts] = useState<AlertRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);

  function loadAlerts() {
    setLoading(true);
    fetchAlerts()
      .then(setAlerts)
      .catch(() => setAlerts([]))
      .finally(() => setLoading(false));
  }

  useEffect(() => { loadAlerts(); }, []);

  async function handleDelete(id: string) {
    await deleteAlert(id).catch(() => {});
    loadAlerts();
  }

  const firing = alerts.filter((a) => a.last_fired);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-[12px] text-text-muted">Threshold-based rules for error rate, latency, and cost.</p>
        <PrimaryButton onClick={() => setModalOpen(true)}><Plus className="h-3.5 w-3.5" /> New Rule</PrimaryButton>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="ui-card overflow-hidden">
          <div className="border-b border-border px-4 py-3"><SectionLabel>Alert Rules</SectionLabel></div>
          <div className="p-4 min-h-[320px]">
            {loading ? (
              <div className="text-[12px] text-text-secondary">Loading alert rules…</div>
            ) : alerts.length === 0 ? (
              <EmptyState
                icon={<Bell className="h-5 w-5 stroke-[1.5]" />}
                title="No alert rules yet"
                description="Create a rule to get notified when error rate, latency, or cost crosses a threshold."
                action={<PrimaryButton onClick={() => setModalOpen(true)}><Plus className="h-3.5 w-3.5" /> Create Rule</PrimaryButton>}
              />
            ) : (
              <div className="table-shell">
                <div className="table-header grid-cols-[minmax(0,1.3fr)_110px_120px_140px_90px_40px]">
                  <span>Rule name</span>
                  <span>Metric</span>
                  <span>Threshold</span>
                  <span>Last triggered</span>
                  <span>Status</span>
                  <span />
                </div>
                {alerts.map((alert) => (
                  <div key={alert.rule_id} className="data-row grid-cols-[minmax(0,1.3fr)_110px_120px_140px_90px_40px] text-[12px]">
                    <span className="truncate font-medium text-text-primary">{alert.name}</span>
                    <span className="text-text-secondary">{alert.condition.split(' ')[0]}</span>
                    <span className="font-mono text-text-secondary">{alert.condition.split(' ').slice(1).join(' ')}</span>
                    <span className="text-text-secondary">{alert.last_fired ? new Date(alert.last_fired).toLocaleString() : 'Never'}</span>
                    <span className="inline-flex items-center gap-2">
                      <StatusDot status={alert.last_fired ? 'warning' : 'success'} />
                      <span className="text-text-secondary">{alert.last_fired ? 'Active' : 'Idle'}</span>
                    </span>
                    <button onClick={() => handleDelete(alert.rule_id)} className="text-text-muted hover:text-danger">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="ui-card overflow-hidden">
          <div className="border-b border-border px-4 py-3"><SectionLabel>Recent Firings</SectionLabel></div>
          <div className="p-4 min-h-[320px]">
            {firing.length === 0 ? (
              <EmptyState
                icon={<BellOff className="h-5 w-5 stroke-[1.5]" />}
                title="No recent firings"
                description="When a rule fires, the last condition and timestamp will appear here."
              />
            ) : (
              <div className="table-shell">
                <div className="table-header grid-cols-[150px_1fr_140px_160px]">
                  <span>Time</span>
                  <span>Rule</span>
                  <span>Trace</span>
                  <span>Condition met</span>
                </div>
                {firing.map((alert) => (
                  <div key={alert.rule_id} className="data-row grid-cols-[150px_1fr_140px_160px] text-[12px]">
                    <span className="text-text-secondary">{new Date(alert.last_fired!).toLocaleString()}</span>
                    <span className="font-medium text-text-primary">{alert.name}</span>
                    <span className="font-mono text-text-muted">{alert.rule_id.slice(0, 8)}</span>
                    <span className="font-mono text-text-secondary">{alert.condition}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {modalOpen && <NewAlertModal onClose={() => setModalOpen(false)} onCreated={() => { setModalOpen(false); loadAlerts(); }} />}
    </div>
  );
}

function NewAlertModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState('');
  const [metric, setMetric] = useState('error_rate');
  const [threshold, setThreshold] = useState('');
  const [webhookUrl, setWebhookUrl] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    if (!name.trim() || !threshold.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await createAlert({
        name: name.trim(),
        condition: `${metric} > ${threshold.trim()}`,
        webhook_url: webhookUrl.trim() || undefined,
      });
      onCreated();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20">
      <div className="w-full max-w-md rounded-lg border border-border bg-surface-900">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div className="text-[14px] font-medium text-text-primary">New Alert Rule</div>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary"><X className="h-4 w-4" /></button>
        </div>
        <div className="space-y-4 p-5">
          <label className="block">
            <div className="section-label mb-1">Rule Name</div>
            <input value={name} onChange={(e) => setName(e.target.value)} className="w-full rounded-md border border-border px-3 py-2 text-[12px] focus:outline-none focus:ring-1 focus:ring-text-muted" />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <div className="section-label mb-1">Metric</div>
              <select value={metric} onChange={(e) => setMetric(e.target.value)} className="w-full rounded-md border border-border px-3 py-2 text-[12px] focus:outline-none focus:ring-1 focus:ring-text-muted">
                {METRIC_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label className="block">
              <div className="section-label mb-1">Threshold</div>
              <input value={threshold} onChange={(e) => setThreshold(e.target.value)} placeholder={METRIC_OPTIONS.find((option) => option.value === metric)?.placeholder} className="w-full rounded-md border border-border px-3 py-2 text-[12px] focus:outline-none focus:ring-1 focus:ring-text-muted" />
            </label>
          </div>
          <label className="block">
            <div className="section-label mb-1">Webhook URL</div>
            <input value={webhookUrl} onChange={(e) => setWebhookUrl(e.target.value)} className="w-full rounded-md border border-border px-3 py-2 text-[12px] focus:outline-none focus:ring-1 focus:ring-text-muted" />
          </label>
          {error && <div className="text-[12px] text-danger">{error}</div>}
        </div>
        <div className="border-t border-border px-5 py-4">
          <OutlineButton onClick={handleSubmit}>{saving ? 'Creating…' : '+ Create Rule'}</OutlineButton>
        </div>
      </div>
    </div>
  );
}
