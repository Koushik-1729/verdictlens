import { useEffect, useState, type ReactNode } from 'react';
import clsx from 'clsx';
import { Check, Copy, Database, Radio, Server } from 'lucide-react';
import { Badge, SectionLabel } from '../components/ui';

const TABS = ['System Status', 'Configuration', 'Integrations', 'Quickstart'] as const;
type TabKey = (typeof TABS)[number];

const SDK_SETUP_SNIPPET = `import verdictlens as vl

vl.configure(
    api_key="vdl_...",  # from Workspaces → API Keys
    workspace="default",
    endpoint="http://localhost:8000",
)

@vl.trace
def my_agent(query: str) -> str:
    ...`;

const INSTRUMENT_SNIPPET = `@vl.trace
def my_agent(query: str) -> str:
    # your agent logic here
    ...`;

const QUICKSTART_STEPS = [
  { step: 1, title: 'Start VerdictLens', code: 'docker compose up -d', multiline: false },
  { step: 2, title: 'Install the SDK', code: 'pip install verdictlens', multiline: false },
  { step: 3, title: 'Configure', code: SDK_SETUP_SNIPPET, multiline: true },
  { step: 4, title: 'Instrument your agent', code: INSTRUMENT_SNIPPET, multiline: true },
  { step: 5, title: 'Open the dashboard', code: 'http://localhost:3000', multiline: false },
];

interface HealthState {
  api: 'healthy' | 'unreachable' | 'checking';
  clickhouse: 'connected' | 'unreachable' | 'checking';
  redis: 'connected' | 'unreachable' | 'checking';
}

export default function Settings() {
  const [activeTab, setActiveTab] = useState<TabKey>('System Status');
  const [health, setHealth] = useState<HealthState>({
    api: 'checking',
    clickhouse: 'checking',
    redis: 'checking',
  });
  const [versions, setVersions] = useState({ api_version: '…', sdk_version: '…' });

  useEffect(() => {
    fetch('/api/health')
      .then((r) => r.json())
      .then((data) => setHealth({
        // 'degraded' means API is up but a dependency is down
        api: data.status === 'ok' || data.status === 'degraded' ? 'healthy' : 'unreachable',
        clickhouse: data.clickhouse === 'connected' ? 'connected' : 'unreachable',
        // 'unavailable' = no Redis URL configured (local mode), treat as OK
        redis: data.redis === 'connected' || data.redis === 'unavailable' ? 'connected' : 'unreachable',
      }))
      .catch(() => setHealth({ api: 'unreachable', clickhouse: 'checking', redis: 'checking' }));

    fetch('/api/version')
      .then((r) => r.json())
      .then((data) => setVersions(data))
      .catch(() => {});
  }, []);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-[rgb(var(--border))] px-6 py-3.5">
        <h1 className="text-[15px] font-semibold text-text-primary">Settings</h1>
        <p className="text-[12px] text-text-muted">Service health, platform details, and runtime configuration.</p>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
      <div className="flex items-center gap-5 border-b border-border">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={clsx(
              'border-b-2 px-1 py-3 text-[12px] font-medium transition-colors',
              activeTab === tab ? 'border-accent text-accent' : 'border-transparent text-text-secondary hover:text-text-primary'
            )}
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === 'System Status' && (
        <div className="space-y-4">
          <div className="grid gap-4 md:grid-cols-3">
            <HealthCard label="API Server" port=":8000" status={health.api} icon={<Server className="h-4 w-4" />} />
            <HealthCard label="ClickHouse" port=":8123" status={health.clickhouse} icon={<Database className="h-4 w-4" />} />
            <HealthCard label="Redis" port=":6379" status={health.redis} icon={<Radio className="h-4 w-4" />} />
          </div>
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
            <div className="ui-card overflow-hidden">
              <div className="border-b border-border px-4 py-3"><SectionLabel>Platform Info</SectionLabel></div>
              <div className="divide-y divide-border">
                {[
                  ['SDK Version', versions.sdk_version],
                  ['API Framework', 'FastAPI + Uvicorn'],
                  ['Trace Storage', 'ClickHouse (columnar)'],
                  ['Pub/Sub', 'Redis (WebSocket fan-out)'],
                  ['License', 'Apache 2.0'],
                ].map(([label, value]) => (
                  <div key={label} className="flex items-center justify-between px-4 py-3 text-[12px]">
                    <span className="text-text-secondary">{label}</span>
                    <span className="font-mono text-text-primary">{value}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="table-shell">
              <div className="table-header grid-cols-[1fr_80px_100px]">
                <span>Service</span>
                <span>Port</span>
                <span>Status</span>
              </div>
              {[
                ['verdictlens-api', ':8000', 'Healthy'],
                ['verdictlens-ui', ':3000', 'Healthy'],
                ['clickhouse', ':8123', 'Connected'],
                ['redis', ':6379', 'Connected'],
              ].map(([service, port, status]) => (
                <div key={service} className="data-row grid-cols-[1fr_80px_100px] text-[12px]">
                  <span className="font-mono text-text-primary">{service}</span>
                  <span className="font-mono text-text-secondary">{port}</span>
                  <span className="text-text-secondary">{status}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {activeTab === 'Configuration' && (
        <div className="ui-card overflow-hidden">
          <div className="border-b border-border px-4 py-3"><SectionLabel>Environment Variables</SectionLabel></div>
          <div className="divide-y divide-border">
            {[
              ['VERDICTLENS_DATABASE_URL', 'postgresql://***@host/db'],
              ['VERDICTLENS_CH_HOST', 'clickhouse'],
              ['VERDICTLENS_CH_PORT', '8123'],
              ['VERDICTLENS_API_KEY', 'Not set'],
              ['VERDICTLENS_DEBUG', 'false'],
              ['VERDICTLENS_DEFAULT_WORKSPACE', 'default'],
            ].map(([key, value]) => (
              <div key={key} className="flex items-center justify-between px-4 py-3 text-[12px]">
                <span className="font-mono text-text-secondary">{key}</span>
                <span className={clsx(
                  'font-mono text-[11px]',
                  key === 'VERDICTLENS_API_KEY' && value === 'Not set' ? 'text-text-muted italic' : 'text-text-primary'
                )}>{value}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {activeTab === 'Integrations' && (
        <div className="space-y-4">
          <div className="ui-card overflow-hidden">
            <div className="border-b border-border px-4 py-3"><SectionLabel>Install</SectionLabel></div>
            <div className="divide-y divide-border">
              {[
                ['Python SDK', 'pip install verdictlens'],
                ['OpenAI', 'pip install "verdictlens[openai]"'],
                ['LangChain', 'pip install "verdictlens[langchain]"'],
                ['CrewAI', 'pip install "verdictlens[crewai]"'],
              ].map(([name, cmd]) => (
                <div key={name} className="flex items-center justify-between gap-3 px-4 py-3">
                  <span className="text-[12px] text-text-primary">{name}</span>
                  <CodeBlock code={cmd} />
                </div>
              ))}
            </div>
          </div>
          <div className="ui-card overflow-hidden">
            <div className="border-b border-border px-4 py-3"><SectionLabel>SDK Setup</SectionLabel></div>
            <div className="px-4 py-3">
              <CodeBlock code={SDK_SETUP_SNIPPET} multiline />
            </div>
          </div>
        </div>
      )}

      {activeTab === 'Quickstart' && (
        <div className="space-y-3">
          {QUICKSTART_STEPS.map(({ step, title, code, multiline }) => (
            <div key={step} className="ui-card overflow-hidden">
              <div className="flex items-center gap-3 border-b border-border px-4 py-3">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[rgb(var(--surface-800))] border border-[rgb(var(--border))] font-mono text-[11px] font-semibold text-text-muted">{step}</span>
                <SectionLabel>{title}</SectionLabel>
              </div>
              <div className="px-4 py-3">
                <CodeBlock code={code} multiline={multiline} />
              </div>
            </div>
          ))}
        </div>
      )}
      </div>
    </div>
  );
}

function HealthCard({
  label,
  port,
  status,
  icon,
}: {
  label: string;
  port: string;
  status: 'healthy' | 'connected' | 'unreachable' | 'checking';
  icon: ReactNode;
}) {
  const badge = status === 'healthy' || status === 'connected'
    ? <Badge variant="clean">{status === 'healthy' ? 'Healthy' : 'Connected'}</Badge>
    : status === 'unreachable'
      ? <Badge variant="originator">Unreachable</Badge>
      : <Badge variant="ambiguous">Checking…</Badge>;

  return (
    <div className="ui-card p-4">
      <div className="flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-md border border-border bg-surface-800 text-text-secondary">{icon}</div>
        <div>
          <div className="text-[13px] font-medium text-text-primary">{label}</div>
          <div className="font-mono text-[11px] text-text-muted">{port}</div>
        </div>
      </div>
      <div className="mt-4 flex items-center justify-between">
        <span className={clsx('h-2 w-2 rounded-full', status === 'healthy' || status === 'connected' ? 'bg-success animate-pulse-slow' : 'bg-danger')} />
        {badge}
      </div>
    </div>
  );
}

function CodeBlock({ code, multiline = false }: { code: string; multiline?: boolean }) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  if (multiline) {
    return (
      <div className="relative rounded-md border border-[rgb(var(--border))] bg-[rgb(var(--surface-800))]">
        <button
          onClick={handleCopy}
          className="absolute right-2 top-2 flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-text-muted transition-colors hover:text-text-primary"
        >
          {copied ? <Check className="h-3 w-3 text-success" /> : <Copy className="h-3 w-3" />}
          {copied ? 'Copied' : 'Copy'}
        </button>
        <pre className="overflow-x-auto px-4 py-3 font-mono text-[11px] text-text-primary leading-relaxed">{code}</pre>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <code className="rounded bg-[rgb(var(--surface-800))] border border-[rgb(var(--border))] px-2 py-1 font-mono text-[11px] text-text-primary">{code}</code>
      <button
        onClick={handleCopy}
        className="flex items-center justify-center rounded p-1 text-text-muted transition-colors hover:text-text-primary"
      >
        {copied ? <Check className="h-3 w-3 text-success" /> : <Copy className="h-3 w-3" />}
      </button>
    </div>
  );
}
