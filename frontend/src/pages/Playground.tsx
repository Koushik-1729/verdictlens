import { useState, useEffect, useCallback, useMemo } from 'react';
import { useLocation } from 'react-router-dom';
import {
  Play,
  Save,
  Clock,
  DollarSign,
  Zap,
  Trash2,
  History,
  ChevronDown,
  ChevronRight,
  Database,
  AlertCircle,
  Loader2,
  Settings2,
  Globe,
  ArrowUpCircle,
  GlobeLock,
  Columns2,
  Variable,
} from 'lucide-react';
import {
  runPlayground,
  savePromptVersion,
  fetchPromptVersions,
  deletePromptVersion,
  fetchVersionHistory,
  publishPrompt,
  unpublishPrompt,
  promotePromptVersion,
  type PlaygroundRunInput,
  type PlaygroundRunResult,
  type PromptVersion,
  type PromptVersionInput,
  type PromptVersionHistory,
} from '../lib/api';
import AddToDatasetModal from '../components/AddToDatasetModal';

const MODELS = [
  { value: 'llama-3.3-70b-versatile', label: 'Llama 3.3 70B (Groq)' },
  { value: 'llama-3.1-8b-instant', label: 'Llama 3.1 8B (Groq)' },
  { value: 'mixtral-8x7b-32768', label: 'Mixtral 8x7B (Groq)' },
  { value: 'gemma2-9b-it', label: 'Gemma 2 9B (Groq)' },
  { value: 'gpt-4o', label: 'GPT-4o (OpenAI)' },
  { value: 'gpt-4o-mini', label: 'GPT-4o Mini (OpenAI)' },
  { value: 'gpt-3.5-turbo', label: 'GPT-3.5 Turbo (OpenAI)' },
  { value: 'claude-3-5-sonnet-20241022', label: 'Claude 3.5 Sonnet' },
  { value: 'claude-3-haiku', label: 'Claude 3 Haiku' },
  { value: 'gemini-1.5-pro', label: 'Gemini 1.5 Pro' },
  { value: 'gemini-1.5-flash', label: 'Gemini 1.5 Flash' },
  { value: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash' },
  { value: 'grok-3', label: 'Grok 3 (xAI)' },
  { value: 'grok-3-mini', label: 'Grok 3 Mini (xAI)' },
];

export default function Playground() {
  const location = useLocation();
  const navState = (location.state || {}) as { prompt?: string; model?: string };

  const [prompt, setPrompt] = useState(navState.prompt || '');
  const [systemMessage, setSystemMessage] = useState('');
  const [model, setModel] = useState(navState.model || 'llama-3.3-70b-versatile');
  const [temperature, setTemperature] = useState(0.7);
  const [maxTokens, setMaxTokens] = useState(1024);

  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<PlaygroundRunResult | null>(null);

  // Variable templating
  const [variables, setVariables] = useState<Record<string, string>>({});
  const detectedVars = useMemo(() => {
    const matches = [...prompt.matchAll(/\{\{(\w+)\}\}/g)];
    return [...new Set(matches.map((m) => m[1]))];
  }, [prompt]);

  // Side-by-side comparison
  const [compareMode, setCompareMode] = useState(false);
  const [modelB, setModelB] = useState('gpt-4o-mini');
  const [resultB, setResultB] = useState<PlaygroundRunResult | null>(null);

  const [versions, setVersions] = useState<PromptVersion[]>([]);
  const [showHistory, setShowHistory] = useState(true);
  const [showSettings, setShowSettings] = useState(true);

  const [saveName, setSaveName] = useState('');
  const [saving, setSaving] = useState(false);

  const [showDatasetModal, setShowDatasetModal] = useState(false);

  const [versionHistory, setVersionHistory] = useState<PromptVersionHistory | null>(null);
  const [historyName, setHistoryName] = useState<string | null>(null);

  const loadVersions = useCallback(async () => {
    try {
      const data = await fetchPromptVersions();
      setVersions(data);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    loadVersions();
  }, [loadVersions]);

  function interpolate(text: string): string {
    return text.replace(/\{\{(\w+)\}\}/g, (_, key) => variables[key] ?? `{{${key}}}`);
  }

  const handleRun = async () => {
    if (!prompt.trim() || running) return;
    setRunning(true);
    setResult(null);
    setResultB(null);

    const finalPrompt = interpolate(prompt);
    const finalSystem = systemMessage ? interpolate(systemMessage) : undefined;

    const bodyA: PlaygroundRunInput = {
      prompt: finalPrompt,
      model,
      temperature,
      max_tokens: maxTokens,
      ...(finalSystem ? { system_message: finalSystem } : {}),
    };

    try {
      if (compareMode) {
        const [resA, resB] = await Promise.all([
          runPlayground(bodyA),
          runPlayground({ ...bodyA, model: modelB }),
        ]);
        setResult(resA);
        setResultB(resB);
      } else {
        const res = await runPlayground(bodyA);
        setResult(res);
      }
    } catch (err: unknown) {
      const errResult = {
        output: null,
        error: err instanceof Error ? err.message : 'Execution failed',
        model,
        latency_ms: 0,
        cost_usd: 0,
        prompt_tokens: 0,
        completion_tokens: 0,
        total_tokens: 0,
      };
      setResult(errResult);
    } finally {
      setRunning(false);
    }
  };

  const handleSave = async () => {
    if (!saveName.trim() || !prompt.trim() || saving) return;
    setSaving(true);
    try {
      const body: PromptVersionInput = {
        name: saveName.trim(),
        content: prompt,
        model,
        temperature,
        max_tokens: maxTokens,
      };
      await savePromptVersion(body);
      setSaveName('');
      await loadVersions();
    } catch {
      /* ignore */
    } finally {
      setSaving(false);
    }
  };

  const loadVersion = (v: PromptVersion) => {
    setPrompt(v.content);
    setModel(v.model);
    setTemperature(v.temperature);
    setMaxTokens(v.max_tokens);
  };

  const handleDeleteVersion = async (id: string) => {
    try {
      await deletePromptVersion(id);
      await loadVersions();
    } catch {
      /* ignore */
    }
  };

  const handleViewHistory = async (name: string) => {
    if (historyName === name) {
      setHistoryName(null);
      setVersionHistory(null);
      return;
    }
    setHistoryName(name);
    try {
      const h = await fetchVersionHistory(name);
      setVersionHistory(h);
    } catch {
      setVersionHistory(null);
    }
  };

  const handlePublish = async (id: string) => {
    try {
      await publishPrompt(id);
      await loadVersions();
      if (historyName) {
        const h = await fetchVersionHistory(historyName);
        setVersionHistory(h);
      }
    } catch {
      /* ignore */
    }
  };

  const handleUnpublish = async (id: string) => {
    try {
      await unpublishPrompt(id);
      await loadVersions();
      if (historyName) {
        const h = await fetchVersionHistory(historyName);
        setVersionHistory(h);
      }
    } catch {
      /* ignore */
    }
  };

  const handlePromote = async (id: string) => {
    try {
      await promotePromptVersion(id);
      await loadVersions();
      if (historyName) {
        const h = await fetchVersionHistory(historyName);
        setVersionHistory(h);
      }
    } catch {
      /* ignore */
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault();
      handleRun();
    }
  };

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-[rgb(var(--border))] px-6 py-3.5">
        <h1 className="text-[15px] font-semibold text-text-primary">Playground</h1>
        <div className="flex items-center gap-2">
          {result?.output && (
            <button
              onClick={() => setShowDatasetModal(true)}
              className="flex items-center gap-1.5 rounded-md border border-[rgb(var(--border))] bg-[rgb(var(--surface-800))] px-2.5 py-1 text-[12px] font-medium text-text-secondary hover:bg-[rgb(var(--surface-700))] hover:text-text-primary transition-colors h-7"
            >
              <Database className="h-3.5 w-3.5" />
              Add to Dataset
            </button>
          )}
          <button
            onClick={() => setCompareMode((c) => !c)}
            className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[12px] font-medium transition-colors h-7 ${compareMode ? 'border-accent/30 bg-accent/5 text-accent' : 'border-[rgb(var(--border))] bg-[rgb(var(--surface-800))] text-text-secondary hover:bg-[rgb(var(--surface-700))]'}`}
          >
            <Columns2 className="h-3.5 w-3.5" />
            Compare
          </button>
          <button
            onClick={() => setShowHistory(!showHistory)}
            className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[12px] font-medium transition-colors h-7 ${showHistory ? 'border-accent/30 bg-accent/5 text-accent' : 'border-[rgb(var(--border))] bg-[rgb(var(--surface-800))] text-text-secondary hover:bg-[rgb(var(--surface-700))]'}`}
          >
            <History className="h-3.5 w-3.5" />
            History
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-5">
      <div className={`grid gap-5 ${showHistory ? 'grid-cols-[1fr_280px]' : 'grid-cols-1'}`}>
        {/* Main editor area */}
        <div className="space-y-4">
          {/* Settings bar */}
          <div className="ui-card p-4">
            <button
              onClick={() => setShowSettings(!showSettings)}
              className="flex items-center gap-2 text-xs font-medium text-text-secondary hover:text-text-primary transition-colors w-full"
            >
              {showSettings ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
              <Settings2 className="h-3.5 w-3.5" />
              Model & Parameters
            </button>
            {showSettings && (
              <div className="grid grid-cols-3 gap-4 mt-3">
                <div>
                  <label className="block text-[10px] uppercase tracking-wider text-text-muted mb-1.5">
                    {compareMode ? 'Model A' : 'Model'}
                  </label>
                  <select
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    className="w-full rounded-md border border-border bg-surface-900 px-3 py-2 text-xs text-text-primary focus:ring-1 focus:ring-accent focus:border-accent"
                  >
                    {MODELS.map((m) => (
                      <option key={m.value} value={m.value}>{m.label}</option>
                    ))}
                  </select>
                </div>
                {compareMode && (
                  <div>
                    <label className="block text-[10px] uppercase tracking-wider text-text-muted mb-1.5">Model B</label>
                    <select
                      value={modelB}
                      onChange={(e) => setModelB(e.target.value)}
                      className="w-full rounded-md border border-border bg-surface-900 px-3 py-2 text-xs text-text-primary focus:ring-1 focus:ring-accent focus:border-accent"
                    >
                      {MODELS.map((m) => (
                        <option key={m.value} value={m.value}>{m.label}</option>
                      ))}
                    </select>
                  </div>
                )}
                <div>
                  <label className="block text-[10px] uppercase tracking-wider text-text-muted mb-1.5">
                    Temperature: {temperature.toFixed(2)}
                  </label>
                  <input
                    type="range"
                    min={0}
                    max={2}
                    step={0.05}
                    value={temperature}
                    onChange={(e) => setTemperature(parseFloat(e.target.value))}
                    className="w-full accent-accent mt-1"
                  />
                </div>
                <div>
                  <label className="block text-[10px] uppercase tracking-wider text-text-muted mb-1.5">Max Tokens</label>
                  <input
                    type="number"
                    min={1}
                    max={4096}
                    value={maxTokens}
                    onChange={(e) => setMaxTokens(parseInt(e.target.value) || 1024)}
                    className="w-full rounded-md border border-border bg-surface-900 px-3 py-2 text-xs text-text-primary focus:ring-1 focus:ring-accent focus:border-accent"
                  />
                </div>
              </div>
            )}
          </div>

          {/* System message */}
          <div className="ui-card p-4">
            <label className="block text-[10px] uppercase tracking-wider text-text-muted mb-1.5">System Message (optional)</label>
            <textarea
              value={systemMessage}
              onChange={(e) => setSystemMessage(e.target.value)}
              placeholder="You are a helpful assistant..."
              rows={2}
              className="w-full rounded-md border border-border bg-surface-900 px-3 py-2 text-xs text-text-primary font-mono placeholder:text-text-muted/50 focus:ring-1 focus:ring-accent focus:border-accent resize-y"
            />
          </div>

          {/* Prompt editor */}
          <div className="ui-card p-4">
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-[10px] uppercase tracking-wider text-text-muted">Prompt</label>
              <span className="text-[10px] text-text-muted">{prompt.length.toLocaleString()} chars</span>
            </div>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Enter your prompt here..."
              rows={8}
              className="w-full rounded-md border border-border bg-surface-900 px-3 py-2 text-sm text-text-primary font-mono placeholder:text-text-muted/50 focus:ring-1 focus:ring-accent focus:border-accent resize-y"
            />
            <div className="flex items-center justify-between mt-3">
              <p className="text-[10px] text-text-muted">Press ⌘+Enter to run</p>
              <button
                onClick={handleRun}
                disabled={!prompt.trim() || running}
                className="flex items-center gap-2 rounded-md bg-accent px-4 py-2 text-xs font-semibold text-white hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                {running ? 'Running...' : 'Run'}
              </button>
            </div>
          </div>

          {/* Variable inputs */}
          {detectedVars.length > 0 && (
            <div className="ui-card p-4">
              <div className="flex items-center gap-2 mb-3">
                <Variable className="h-3.5 w-3.5 text-text-muted" />
                <span className="text-[10px] uppercase tracking-wider text-text-muted font-medium">Variables</span>
              </div>
              <div className="grid grid-cols-2 gap-3">
                {detectedVars.map((v) => (
                  <div key={v}>
                    <label className="block text-[11px] text-text-muted mb-1 font-mono">{`{{${v}}}`}</label>
                    <input
                      type="text"
                      value={variables[v] ?? ''}
                      onChange={(e) => setVariables((prev) => ({ ...prev, [v]: e.target.value }))}
                      placeholder={`Value for ${v}`}
                      className="w-full rounded-md border border-border bg-surface-900 px-3 py-1.5 text-xs text-text-primary placeholder:text-text-muted/50 focus:ring-1 focus:ring-accent focus:border-accent"
                    />
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Result */}
          {result && !resultB && (
            <div className="ui-card p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-semibold text-text-primary uppercase tracking-wider">Response</h3>
                <div className="flex items-center gap-3 text-[10px] text-text-muted">
                  <span className="flex items-center gap-1"><Zap className="h-3 w-3" />{result.model}</span>
                  <span className="flex items-center gap-1"><Clock className="h-3 w-3" />{result.latency_ms.toFixed(0)}ms</span>
                  {result.total_tokens > 0 && <span>{result.prompt_tokens}+{result.completion_tokens}={result.total_tokens} tok</span>}
                  {result.cost_usd > 0 && <span className="flex items-center gap-1"><DollarSign className="h-3 w-3" />${result.cost_usd.toFixed(4)}</span>}
                </div>
              </div>
              {result.error ? (
                <div className="rounded-md border border-danger/20 bg-danger/5 p-3 flex items-start gap-2">
                  <AlertCircle className="h-4 w-4 text-danger mt-0.5 flex-shrink-0" />
                  <pre className="text-xs text-danger whitespace-pre-wrap font-mono">{result.error}</pre>
                </div>
              ) : (
                <div className="rounded-md border border-border bg-surface-900 p-3">
                  <pre className="text-sm text-text-primary whitespace-pre-wrap font-mono leading-relaxed">{result.output || '(empty response)'}</pre>
                </div>
              )}
            </div>
          )}

          {result && resultB && (
            <div className="grid grid-cols-2 gap-3">
              {[result, resultB].map((r, i) => (
                <div key={i} className="ui-card p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-text-muted">Model {i === 0 ? 'A' : 'B'}</span>
                    <div className="flex items-center gap-2 text-[10px] text-text-muted">
                      <span className="font-mono">{r.model}</span>
                      <span>{r.latency_ms.toFixed(0)}ms</span>
                      {r.cost_usd > 0 && <span>${r.cost_usd.toFixed(4)}</span>}
                    </div>
                  </div>
                  {r.error ? (
                    <div className="rounded-md border border-danger/20 bg-danger/5 p-3 flex items-start gap-2">
                      <AlertCircle className="h-3.5 w-3.5 text-danger mt-0.5 flex-shrink-0" />
                      <pre className="text-xs text-danger whitespace-pre-wrap font-mono">{r.error}</pre>
                    </div>
                  ) : (
                    <div className="rounded-md border border-border bg-surface-900 p-3">
                      <pre className="text-xs text-text-primary whitespace-pre-wrap font-mono leading-relaxed">{r.output || '(empty response)'}</pre>
                    </div>
                  )}
                  {r.total_tokens > 0 && (
                    <div className="text-[10px] text-text-muted">{r.prompt_tokens}+{r.completion_tokens}={r.total_tokens} tokens</div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Save prompt */}
          <div className="ui-card p-4">
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={saveName}
                onChange={(e) => setSaveName(e.target.value)}
                placeholder="Prompt name..."
                className="flex-1 rounded-md border border-border bg-surface-900 px-3 py-2 text-xs text-text-primary placeholder:text-text-muted/50 focus:ring-1 focus:ring-accent focus:border-accent"
                onKeyDown={(e) => { if (e.key === 'Enter') handleSave(); }}
              />
              <button
                onClick={handleSave}
                disabled={!saveName.trim() || !prompt.trim() || saving}
                className="flex items-center gap-1.5 rounded-md border border-border bg-surface-800 px-3 py-2 text-xs font-medium text-text-secondary hover:bg-surface-700 hover:text-text-primary disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <Save className="h-3.5 w-3.5" />
                {saving ? 'Saving...' : 'Save Version'}
              </button>
            </div>
          </div>
        </div>

        {/* History sidebar */}
        {showHistory && (
          <div className="space-y-2">
            <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wider px-1">
              Saved Prompts ({versions.length})
            </h3>
            {versions.length === 0 ? (
              <div className="ui-card p-4 text-center">
                <History className="h-6 w-6 text-text-muted mx-auto mb-2" />
                <p className="text-xs text-text-muted">No saved prompts yet</p>
              </div>
            ) : (
              <div className="space-y-1.5 max-h-[calc(100vh-220px)] overflow-y-auto">
                {versions.map((v) => (
                  <div key={v.id} className="ui-card p-3 group hover:border-accent/20 cursor-pointer transition-colors">
                    <div className="flex items-start justify-between gap-2" onClick={() => loadVersion(v)}>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <p className="text-xs font-medium text-text-primary truncate">{v.name}</p>
                          {v.is_published && (
                            <span title="Published"><Globe className="h-3 w-3 text-success flex-shrink-0" /></span>
                          )}
                        </div>
                        <p className="text-[10px] text-text-muted mt-0.5">
                          v{v.version_number} · {v.model}
                        </p>
                        <p className="text-[10px] text-text-muted line-clamp-2 mt-1 font-mono">{v.content}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-1 mt-2 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={(e) => { e.stopPropagation(); handleViewHistory(v.name); }}
                        className="rounded px-1.5 py-0.5 text-[9px] text-text-muted hover:bg-surface-700 hover:text-text-primary transition-colors"
                        title="Version history"
                      >
                        <History className="h-3 w-3" />
                      </button>
                      {v.is_published ? (
                        <button
                          onClick={(e) => { e.stopPropagation(); handleUnpublish(v.id); }}
                          className="rounded px-1.5 py-0.5 text-[9px] text-success hover:bg-surface-700 transition-colors"
                          title="Unpublish"
                        >
                          <GlobeLock className="h-3 w-3" />
                        </button>
                      ) : (
                        <button
                          onClick={(e) => { e.stopPropagation(); handlePublish(v.id); }}
                          className="rounded px-1.5 py-0.5 text-[9px] text-text-muted hover:bg-surface-700 hover:text-success transition-colors"
                          title="Publish to Hub"
                        >
                          <Globe className="h-3 w-3" />
                        </button>
                      )}
                      {v.version_number > 1 && (
                        <button
                          onClick={(e) => { e.stopPropagation(); handlePromote(v.id); }}
                          className="rounded px-1.5 py-0.5 text-[9px] text-text-muted hover:bg-surface-700 hover:text-accent transition-colors"
                          title="Promote to latest"
                        >
                          <ArrowUpCircle className="h-3 w-3" />
                        </button>
                      )}
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDeleteVersion(v.id); }}
                        className="rounded px-1.5 py-0.5 text-[9px] text-text-muted hover:bg-surface-700 hover:text-danger transition-colors ml-auto"
                        title="Delete"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                    {v.tags.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1.5">
                        {v.tags.map((t) => (
                          <span key={t} className="rounded bg-accent/10 px-1.5 py-0.5 text-[9px] text-accent">{t}</span>
                        ))}
                      </div>
                    )}
                    <p className="text-[9px] text-text-muted mt-1">
                      {new Date(v.created_at || '').toLocaleString()}
                    </p>
                  </div>
                ))}
              </div>
            )}

            {/* Version history panel */}
            {historyName && versionHistory && (
              <div className="ui-card p-3 mt-2 space-y-2">
                <div className="flex items-center justify-between">
                  <h4 className="text-[10px] uppercase tracking-wider text-text-muted font-semibold">
                    History: {historyName}
                  </h4>
                  <span className="text-[9px] text-text-muted">{versionHistory.total_versions} versions</span>
                </div>
                <div className="space-y-1 max-h-48 overflow-y-auto">
                  {versionHistory.versions.map((hv) => (
                    <div
                      key={hv.id}
                      className="flex items-center justify-between gap-2 rounded-md border border-border bg-surface-900 px-2.5 py-1.5 cursor-pointer hover:bg-surface-800 transition-colors"
                      onClick={() => loadVersion(hv)}
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <span className="text-[10px] font-medium text-text-primary">v{hv.version_number}</span>
                          {hv.is_published && <Globe className="h-2.5 w-2.5 text-success" />}
                          <span className="text-[9px] text-text-muted">{hv.model}</span>
                        </div>
                      </div>
                      <span className="text-[9px] text-text-muted flex-shrink-0">
                        {new Date(hv.created_at || '').toLocaleDateString()}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      </div>

      {showDatasetModal && result?.trace_id && (
        <AddToDatasetModal
          traceId={result.trace_id}
          onClose={() => setShowDatasetModal(false)}
        />
      )}
    </div>
  );
}
