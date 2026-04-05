import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  BookOpen,
  Zap,
  Clock,
  DollarSign,
  Hash,
  Layers,
  Search,
  FlaskConical,
  BarChart3,
} from 'lucide-react';
import {
  fetchHubPrompts,
  fetchPromptUsageStats,
  type PromptHubEntry,
  type PromptUsageStats,
} from '../lib/api';

export default function PromptHub() {
  const navigate = useNavigate();
  const [prompts, setPrompts] = useState<PromptHubEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [selectedPrompt, setSelectedPrompt] = useState<PromptHubEntry | null>(null);
  const [usageStats, setUsageStats] = useState<PromptUsageStats | null>(null);
  const [loadingStats, setLoadingStats] = useState(false);

  const loadPrompts = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchHubPrompts();
      setPrompts(data);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPrompts();
  }, [loadPrompts]);

  const handleSelectPrompt = async (p: PromptHubEntry) => {
    setSelectedPrompt(p);
    setLoadingStats(true);
    try {
      const stats = await fetchPromptUsageStats(p.name);
      setUsageStats(stats);
    } catch {
      setUsageStats(null);
    } finally {
      setLoadingStats(false);
    }
  };

  const openInPlayground = (p: PromptHubEntry) => {
    navigate('/playground', { state: { prompt: p.content, model: p.model } });
  };

  const filtered = prompts.filter((p) =>
    p.name.toLowerCase().includes(search.toLowerCase()) ||
    p.tags.some((t) => t.toLowerCase().includes(search.toLowerCase()))
  );

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-6 py-3.5">
        <div className="flex items-center gap-2">
          <h1 className="text-[15px] font-semibold text-text-primary">Prompt Hub</h1>
          {!loading && (
            <span className="rounded-full bg-surface-700 px-2 py-0.5 text-[11px] font-medium text-text-muted">
              {filtered.length}
            </span>
          )}
        </div>
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-text-muted" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search prompts or tags..."
            className="h-7 w-52 rounded-md border border-border bg-surface-900 pl-8 pr-3 text-[12px] text-text-primary placeholder:text-text-muted/50 focus:ring-1 focus:ring-accent focus:border-accent"
          />
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-5 space-y-5">
        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {[1, 2, 3, 4, 5, 6].map((i) => (
              <div key={i} className="ui-card p-5 animate-pulse">
                <div className="h-4 w-32 bg-surface-700 rounded mb-3" />
                <div className="h-3 w-full bg-surface-700 rounded mb-2" />
                <div className="h-3 w-2/3 bg-surface-700 rounded" />
              </div>
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div className="ui-card p-12 text-center">
            <BookOpen className="h-10 w-10 text-text-muted mx-auto mb-3" />
            <h3 className="text-sm font-medium text-text-primary mb-1">
              {prompts.length === 0 ? 'No published prompts yet' : 'No matching prompts'}
            </h3>
            <p className="text-xs text-text-muted">
              {prompts.length === 0
                ? 'Save and publish prompts from the Playground to share them with your team.'
                : 'Try a different search term.'}
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filtered.map((p) => (
              <div
                key={p.id}
                onClick={() => handleSelectPrompt(p)}
                className={`ui-card p-5 cursor-pointer transition-all hover:border-accent/20 ${selectedPrompt?.id === p.id ? 'border-accent/30 ring-1 ring-accent/20' : ''}`}
              >
                <div className="flex items-start justify-between gap-2 mb-3">
                  <div className="min-w-0 flex-1">
                    <h3 className="text-sm font-semibold text-text-primary truncate">{p.name}</h3>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="inline-flex items-center gap-1 rounded bg-accent/10 px-1.5 py-0.5 text-[10px] font-medium text-accent">
                        <Zap className="h-2.5 w-2.5" />
                        {p.model}
                      </span>
                      <span className="text-[10px] text-text-muted">v{p.version_number}</span>
                    </div>
                  </div>
                  <button
                    onClick={(e) => { e.stopPropagation(); openInPlayground(p); }}
                    className="rounded-md border border-border bg-surface-800 px-2.5 py-1 text-[10px] font-medium text-text-secondary hover:bg-surface-700 hover:text-text-primary transition-colors flex-shrink-0"
                  >
                    <FlaskConical className="h-3 w-3" />
                  </button>
                </div>

                <p className="text-xs text-text-muted font-mono line-clamp-3 mb-3">{p.content}</p>

                {p.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1 mb-3">
                    {p.tags.map((t) => (
                      <span key={t} className="rounded bg-surface-700 px-1.5 py-0.5 text-[9px] text-text-muted">
                        {t}
                      </span>
                    ))}
                  </div>
                )}

                <div className="flex items-center gap-3 text-[10px] text-text-muted border-t border-border pt-2.5">
                  <span className="flex items-center gap-1">
                    <Layers className="h-3 w-3" />
                    {p.total_versions} version{p.total_versions !== 1 ? 's' : ''}
                  </span>
                  <span className="flex items-center gap-1">
                    <Hash className="h-3 w-3" />
                    {p.usage_count} run{p.usage_count !== 1 ? 's' : ''}
                  </span>
                  {p.created_at && (
                    <span className="ml-auto">
                      {new Date(p.created_at).toLocaleDateString()}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Detail panel */}
        {selectedPrompt && (
          <div className="ui-card p-5 space-y-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-base font-semibold text-text-primary">{selectedPrompt.name}</h2>
                <div className="flex items-center gap-2 mt-1 text-xs text-text-muted">
                  <span>{selectedPrompt.model}</span>
                  <span>·</span>
                  <span>temp {selectedPrompt.temperature}</span>
                  <span>·</span>
                  <span>max {selectedPrompt.max_tokens} tok</span>
                  <span>·</span>
                  <span>v{selectedPrompt.version_number}</span>
                </div>
              </div>
              <button
                onClick={() => openInPlayground(selectedPrompt)}
                className="flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-white hover:bg-accent/90 transition-colors"
              >
                <FlaskConical className="h-3.5 w-3.5" />
                Open in Playground
              </button>
            </div>

            <div className="rounded-md border border-border bg-surface-900 p-3">
              <pre className="text-xs text-text-primary whitespace-pre-wrap font-mono leading-relaxed">
                {selectedPrompt.content}
              </pre>
            </div>

            {/* Usage stats */}
            {loadingStats ? (
              <div className="grid grid-cols-4 gap-3">
                {[1, 2, 3, 4].map((i) => (
                  <div key={i} className="rounded-lg border border-border bg-surface-900 p-3 animate-pulse">
                    <div className="h-3 w-16 bg-surface-700 rounded mb-2" />
                    <div className="h-5 w-12 bg-surface-700 rounded" />
                  </div>
                ))}
              </div>
            ) : usageStats ? (
              <div className="grid grid-cols-4 gap-3">
                <div className="rounded-lg border border-border bg-surface-900 p-3">
                  <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-text-muted mb-1">
                    <BarChart3 className="h-3 w-3" />
                    Total Runs
                  </div>
                  <p className="text-lg font-semibold text-text-primary">{usageStats.total_runs.toLocaleString()}</p>
                </div>
                <div className="rounded-lg border border-border bg-surface-900 p-3">
                  <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-text-muted mb-1">
                    <Zap className="h-3 w-3" />
                    Total Tokens
                  </div>
                  <p className="text-lg font-semibold text-text-primary">{usageStats.total_tokens.toLocaleString()}</p>
                </div>
                <div className="rounded-lg border border-border bg-surface-900 p-3">
                  <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-text-muted mb-1">
                    <DollarSign className="h-3 w-3" />
                    Total Cost
                  </div>
                  <p className="text-lg font-semibold text-text-primary">${usageStats.total_cost_usd.toFixed(4)}</p>
                </div>
                <div className="rounded-lg border border-border bg-surface-900 p-3">
                  <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-text-muted mb-1">
                    <Clock className="h-3 w-3" />
                    Avg Latency
                  </div>
                  <p className="text-lg font-semibold text-text-primary">{usageStats.avg_latency_ms.toFixed(0)}ms</p>
                </div>
              </div>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}
