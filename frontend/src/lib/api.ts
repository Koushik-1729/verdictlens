const BASE = import.meta.env.VITE_API_URL ?? '/api';

const AUTH_STORAGE_KEY = 'verdictlens_api_key';
const WORKSPACE_STORAGE_KEY = 'verdictlens_workspace';

export function getStoredApiKey(): string | null {
  return localStorage.getItem(AUTH_STORAGE_KEY);
}

export function setStoredApiKey(key: string): void {
  localStorage.setItem(AUTH_STORAGE_KEY, key);
}

export function clearStoredApiKey(): void {
  localStorage.removeItem(AUTH_STORAGE_KEY);
}

export function getCurrentWorkspace(): string {
  return localStorage.getItem(WORKSPACE_STORAGE_KEY) || 'default';
}

export function setCurrentWorkspace(workspace: string): void {
  localStorage.setItem(WORKSPACE_STORAGE_KEY, workspace);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${BASE}${path}`;
  const apiKey = getStoredApiKey();
  const workspace = getCurrentWorkspace();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-VerdictLens-Workspace': workspace,
    ...(init?.headers as Record<string, string>),
  };
  if (apiKey) {
    headers['X-VerdictLens-Key'] = apiKey;
  }
  const res = await fetch(url, { ...init, headers });
  if (res.status === 401) {
    window.dispatchEvent(new CustomEvent('verdictlens:auth-required'));
    throw new Error('Unauthorized');
  }
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`API ${res.status}: ${text.slice(0, 256)}`);
  }
  return res.json();
}

export interface TokenUsage {
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
}

export interface ErrorDetail {
  type: string;
  message: string;
  stack: string | null;
}

export function formatError(err: ErrorDetail | string | null | undefined): string {
  if (!err) return 'Unknown error';
  if (typeof err === 'string') return err;
  return `${err.type}: ${err.message}`;
}

export interface Span {
  span_id: string;
  parent_span_id: string | null;
  trace_id: string;
  name: string;
  span_type: string;
  start_time: string | null;
  end_time: string | null;
  latency_ms: number | null;
  model: string | null;
  input: unknown;
  output: unknown;
  decision: string | null;
  confidence_score: number | null;
  token_usage: TokenUsage | null;
  cost_usd: number | null;
  error: ErrorDetail | string | null;
  metadata: Record<string, unknown>;
}

export interface TraceSummary {
  trace_id: string;
  name: string;
  start_time: string | null;
  end_time: string | null;
  latency_ms: number | null;
  status: string;
  framework: string | null;
  model: string | null;
  cost_usd: number | null;
  error: ErrorDetail | string | null;
  span_count: number;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  metadata: Record<string, unknown>;
}

export interface TraceDetail extends Omit<TraceSummary, 'span_count'> {
  input: unknown;
  output: unknown;
  token_usage: TokenUsage | null;
  spans: Span[];
}

export interface TraceListResponse {
  traces: TraceSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface Metrics {
  total_traces: number;
  total_spans: number;
  total_cost_usd: number;
  total_tokens: number;
  avg_latency_ms: number | null;
  error_rate: number;
  traces_by_status: Record<string, number>;
  traces_by_framework: Record<string, number>;
  traces_by_model: Record<string, number>;
  cost_by_model: Record<string, number>;
  hourly_trace_counts: { hour: string; count: number }[];
  token_breakdown_by_model: Record<string, { prompt: number; completion: number }>;
}

export interface TraceFilters {
  page?: number;
  page_size?: number;
  status?: string;
  framework?: string;
  name?: string;
  model?: string;
  start_after?: string;
  start_before?: string;
}

export function searchTraces(q: string, page = 1, pageSize = 50): Promise<TraceListResponse> {
  const params = new URLSearchParams({ q, page: String(page), page_size: String(pageSize) });
  return request<TraceListResponse>(`/traces/search?${params}`);
}

export function fetchTraces(filters: TraceFilters = {}): Promise<TraceListResponse> {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') params.set(k, String(v));
  });
  const qs = params.toString();
  return request<TraceListResponse>(`/traces${qs ? `?${qs}` : ''}`);
}

export function fetchTrace(id: string): Promise<TraceDetail> {
  return request<TraceDetail>(`/traces/${encodeURIComponent(id)}`);
}

export function fetchMetrics(hours = 24): Promise<Metrics> {
  return request<Metrics>(`/metrics?hours=${hours}`);
}

export interface BlameSpan {
  span_id: string;
  span_name: string;
  role: string;
  blame_score: number;
  reason: string;
  caused_by: string | null;
}

export interface BlameResult {
  originators: BlameSpan[];
  failure_points: BlameSpan[];
  secondary_contributors: BlameSpan[];
  propagation_chain: string[];
  confidence: string;
  human_summary: string;
  retry_storm: boolean;
  full_chain: Span[];
}

export function fetchBlame(traceId: string): Promise<BlameResult> {
  return request<BlameResult>(`/traces/${encodeURIComponent(traceId)}/blame`);
}

export interface ParentContextEntry {
  span_id: string;
  name: string;
  span_type: string;
  input_summary: string | null;
  output_summary: string | null;
  decision: string | null;
}

export interface TreePosition {
  depth: number;
  parent_span_id: string | null;
  is_root: boolean;
  sibling_count: number;
}

export interface ReplayResult {
  original_span_id: string;
  replay_span_id: string;
  original_input: Record<string, unknown> | null;
  new_input: Record<string, unknown>;
  original_output: unknown;
  new_output: unknown;
  original_latency_ms: number;
  new_latency_ms: number;
  original_cost_usd: number;
  new_cost_usd: number;
  original_tokens: number;
  new_tokens: number;
  output_diff: string[];
  status: 'same' | 'improved' | 'degraded' | 'different';
  improvement_score: number | null;
  note: string | null;
  parent_context: { chain: ParentContextEntry[] } | null;
  tree_position: TreePosition | null;
}

export interface ReplaySummary {
  replay_span_id: string;
  original_span_id: string;
  original_span_name: string;
  note: string | null;
  status: 'same' | 'improved' | 'degraded' | 'different';
  created_at: string;
}

export function submitReplay(
  traceId: string,
  spanId: string,
  newInput: Record<string, unknown>,
  note?: string,
): Promise<ReplayResult> {
  return request<ReplayResult>(
    `/traces/${encodeURIComponent(traceId)}/spans/${encodeURIComponent(spanId)}/replay`,
    { method: 'POST', body: JSON.stringify({ new_input: newInput, note: note || null }) },
  );
}

export function fetchReplays(traceId: string): Promise<ReplaySummary[]> {
  return request<ReplaySummary[]>(`/traces/${encodeURIComponent(traceId)}/replays`);
}

// ---------------------------------------------------------------------------
// Alerts
// ---------------------------------------------------------------------------

export interface AlertRule {
  rule_id: string;
  name: string;
  condition: string;
  window_minutes: number;
  channels: string[];
  webhook_url: string | null;
  created_at: string;
  last_fired: string | null;
}

export interface AlertRuleInput {
  name: string;
  condition: string;
  window_minutes?: number;
  channels?: string[];
  webhook_url?: string;
}

export function fetchAlerts(): Promise<AlertRule[]> {
  return request<AlertRule[]>('/alerts');
}

export function createAlert(rule: AlertRuleInput): Promise<AlertRule> {
  return request<AlertRule>('/alerts', {
    method: 'POST',
    body: JSON.stringify(rule),
  });
}

export function deleteAlert(ruleId: string): Promise<{ status: string }> {
  return request<{ status: string }>(`/alerts/${encodeURIComponent(ruleId)}`, {
    method: 'DELETE',
  });
}

// ---------------------------------------------------------------------------
// Datasets
// ---------------------------------------------------------------------------

export interface Dataset {
  id: string;
  name: string;
  description: string;
  workspace_id: string;
  project_name: string;
  created_at: string;
  example_count: number;
}

export interface DatasetInput {
  name: string;
  description?: string;
}

export interface DatasetExample {
  id: string;
  dataset_id: string;
  inputs: unknown;
  outputs: unknown;
  expected: unknown;
  metadata: Record<string, unknown>;
  source_trace_id: string | null;
  source_span_id: string | null;
  created_at: string;
  split: string;
}

export interface ExampleInput {
  inputs: unknown;
  outputs?: unknown;
  expected?: unknown;
  metadata?: Record<string, unknown>;
}

export interface TraceToDatasetInput {
  dataset_id: string;
  span_id?: string;
  expected?: unknown;
}

export function fetchDatasets(): Promise<Dataset[]> {
  return request<Dataset[]>('/datasets');
}

export function fetchDataset(id: string): Promise<Dataset> {
  return request<Dataset>(`/datasets/${encodeURIComponent(id)}`);
}

export function createDataset(body: DatasetInput): Promise<Dataset> {
  return request<Dataset>('/datasets', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function deleteDataset(id: string): Promise<{ status: string }> {
  return request<{ status: string }>(`/datasets/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}

export function fetchExamples(datasetId: string): Promise<DatasetExample[]> {
  return request<DatasetExample[]>(`/datasets/${encodeURIComponent(datasetId)}/examples`);
}

export function addExample(datasetId: string, body: ExampleInput): Promise<DatasetExample> {
  return request<DatasetExample>(`/datasets/${encodeURIComponent(datasetId)}/examples`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function deleteExample(datasetId: string, exampleId: string): Promise<{ status: string }> {
  return request<{ status: string }>(
    `/datasets/${encodeURIComponent(datasetId)}/examples/${encodeURIComponent(exampleId)}`,
    { method: 'DELETE' },
  );
}

export function traceToDataset(traceId: string, body: TraceToDatasetInput): Promise<DatasetExample> {
  return request<DatasetExample>(`/traces/${encodeURIComponent(traceId)}/to-dataset`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

// ---------------------------------------------------------------------------
// Evaluations
// ---------------------------------------------------------------------------

export interface ScorerConfig {
  type: 'exact_match' | 'contains' | 'llm_judge' | 'custom' | 'regex' | 'json_match';
  model?: string;
  prompt_template?: string;
  field?: string;
  threshold?: number;
}

export interface EvaluationInput {
  name: string;
  dataset_id: string;
  scorers?: ScorerConfig[];
  mode?: 'replay' | 'live';
}

export interface Evaluation {
  id: string;
  name: string;
  dataset_id: string;
  workspace_id: string;
  scorer_config: ScorerConfig[];
  mode: string;
  status: string;
  created_at: string;
  completed_at: string | null;
  total: number;
  passed: number;
  failed: number;
  average_score: number;
}

export interface EvalResult {
  id: string;
  eval_id: string;
  example_id: string;
  score: number;
  passed: boolean;
  output: unknown;
  latency_ms: number;
  cost_usd: number;
  created_at: string;
}

export interface CompareExampleDiff {
  example_id: string;
  score_a: number;
  score_b: number;
  passed_a: boolean;
  passed_b: boolean;
  delta: number;
}

export interface CompareResult {
  eval_a_id: string;
  eval_b_id: string;
  eval_a_name: string;
  eval_b_name: string;
  wins: number;
  losses: number;
  ties: number;
  diffs: CompareExampleDiff[];
}

export function fetchEvaluations(): Promise<Evaluation[]> {
  return request<Evaluation[]>('/evaluations');
}

export function fetchEvaluation(id: string): Promise<Evaluation> {
  return request<Evaluation>(`/evaluations/${encodeURIComponent(id)}`);
}

export function createEvaluation(body: EvaluationInput): Promise<Evaluation> {
  return request<Evaluation>('/evaluations', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function deleteEvaluation(id: string): Promise<{ status: string }> {
  return request<{ status: string }>(`/evaluations/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}

export function fetchEvalResults(evalId: string): Promise<EvalResult[]> {
  return request<EvalResult[]>(`/evaluations/${encodeURIComponent(evalId)}/results`);
}

export function compareEvaluations(evalA: string, evalB: string): Promise<CompareResult> {
  return request<CompareResult>(`/evaluations/compare?eval_a=${encodeURIComponent(evalA)}&eval_b=${encodeURIComponent(evalB)}`);
}

export interface EvalCIStatus {
  eval_id: string;
  name: string;
  score: number;
  threshold: number;
  passed: boolean;
  total: number;
  passed_count: number;
  failed_count: number;
  status: string;
  exit_code: number;
}

export function fetchEvalCIStatus(evalId: string, threshold = 0.8): Promise<EvalCIStatus> {
  return request<EvalCIStatus>(`/evaluations/${encodeURIComponent(evalId)}/ci?threshold=${threshold}`);
}

// ---------------------------------------------------------------------------
// Workspaces & API Keys
// ---------------------------------------------------------------------------

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  description: string;
  created_at: string;
}

export interface WorkspaceInput {
  name: string;
  slug: string;
  description?: string;
}

export interface ApiKey {
  id: string;
  name: string;
  workspace_id: string;
  key_prefix: string;
  key?: string;
  created_at: string;
}

export interface ApiKeyInput {
  name: string;
  workspace_id: string;
}

export function fetchWorkspaces(): Promise<Workspace[]> {
  return request<Workspace[]>('/workspaces');
}

export function createWorkspace(body: WorkspaceInput): Promise<Workspace> {
  return request<Workspace>('/workspaces', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function fetchApiKeys(workspaceId: string): Promise<ApiKey[]> {
  return request<ApiKey[]>(`/workspaces/${encodeURIComponent(workspaceId)}/api-keys`);
}

export function createApiKey(workspaceId: string, body: { name: string }): Promise<ApiKey> {
  return request<ApiKey>(`/workspaces/${encodeURIComponent(workspaceId)}/api-keys`, {
    method: 'POST',
    body: JSON.stringify({ ...body, workspace_id: workspaceId }),
  });
}

export function deleteApiKey(workspaceId: string, keyId: string): Promise<{ status: string }> {
  return request<{ status: string }>(
    `/workspaces/${encodeURIComponent(workspaceId)}/api-keys/${encodeURIComponent(keyId)}`,
    { method: 'DELETE' },
  );
}

// ---------------------------------------------------------------------------
// Prompt Playground (Phase 4)
// ---------------------------------------------------------------------------

export interface PlaygroundRunInput {
  prompt: string;
  model?: string;
  temperature?: number;
  max_tokens?: number;
  system_message?: string;
  prompt_version_id?: string;
}

export interface PlaygroundRunResult {
  output: string | null;
  error: string | null;
  model: string;
  latency_ms: number;
  cost_usd: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  trace_id?: string;
}

export interface PromptVersionInput {
  name: string;
  content: string;
  model?: string;
  temperature?: number;
  max_tokens?: number;
  parent_id?: string;
  tags?: string[];
}

export interface PromptVersion {
  id: string;
  name: string;
  content: string;
  model: string;
  temperature: number;
  max_tokens: number;
  workspace_id: string;
  version_number: number;
  parent_id: string | null;
  tags: string[];
  is_published: boolean;
  created_at: string;
}

export function runPlayground(body: PlaygroundRunInput): Promise<PlaygroundRunResult> {
  return request<PlaygroundRunResult>('/playground/run', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function savePromptVersion(body: PromptVersionInput): Promise<PromptVersion> {
  return request<PromptVersion>('/playground/prompts', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function fetchPromptVersions(): Promise<PromptVersion[]> {
  return request<PromptVersion[]>('/playground/prompts');
}

export function fetchPromptVersion(versionId: string): Promise<PromptVersion> {
  return request<PromptVersion>(`/playground/prompts/${encodeURIComponent(versionId)}`);
}

export function deletePromptVersion(versionId: string): Promise<{ status: string }> {
  return request<{ status: string }>(
    `/playground/prompts/${encodeURIComponent(versionId)}`,
    { method: 'DELETE' },
  );
}

// ---------------------------------------------------------------------------
// Prompt Hub (Phase 5)
// ---------------------------------------------------------------------------

export interface PromptVersionHistory {
  name: string;
  workspace_id: string;
  versions: PromptVersion[];
  total_versions: number;
  latest_version: PromptVersion | null;
}

export interface PromptHubEntry {
  id: string;
  name: string;
  content: string;
  model: string;
  temperature: number;
  max_tokens: number;
  workspace_id: string;
  version_number: number;
  tags: string[];
  created_at: string;
  total_versions: number;
  usage_count: number;
}

export interface PromptUsageStats {
  prompt_name: string;
  total_runs: number;
  total_tokens: number;
  total_cost_usd: number;
  avg_latency_ms: number;
  last_used: string | null;
}

export function fetchVersionHistory(name: string): Promise<PromptVersionHistory> {
  return request<PromptVersionHistory>(`/playground/prompts/${encodeURIComponent(name)}/history`);
}

export function publishPrompt(versionId: string): Promise<{ status: string }> {
  return request<{ status: string }>(
    `/playground/prompts/${encodeURIComponent(versionId)}/publish`,
    { method: 'POST' },
  );
}

export function unpublishPrompt(versionId: string): Promise<{ status: string }> {
  return request<{ status: string }>(
    `/playground/prompts/${encodeURIComponent(versionId)}/unpublish`,
    { method: 'POST' },
  );
}

export function promotePromptVersion(versionId: string): Promise<PromptVersion> {
  return request<PromptVersion>(
    `/playground/prompts/${encodeURIComponent(versionId)}/promote`,
    { method: 'POST' },
  );
}

export function fetchHubPrompts(): Promise<PromptHubEntry[]> {
  return request<PromptHubEntry[]>('/prompt-hub');
}

export function fetchPromptUsageStats(promptName: string): Promise<PromptUsageStats> {
  return request<PromptUsageStats>(`/prompt-hub/${encodeURIComponent(promptName)}/usage`);
}

export interface HubPullResult {
  name: string;
  content: string;
  model: string;
  temperature: number;
  max_tokens: number;
  version_number: number;
  tags: string[];
}

export function pullPrompt(name: string, version?: number): Promise<HubPullResult> {
  const qs = version != null ? `?version=${version}` : '';
  return request<HubPullResult>(`/prompt-hub/${encodeURIComponent(name)}/pull${qs}`);
}

// ---------------------------------------------------------------------------
// Monitoring Dashboard
// ---------------------------------------------------------------------------

export interface TimeSeriesPoint {
  ts: string;
  value: number;
  value2?: number | null;
  label?: string | null;
}

export interface LatencyPercentilesPoint {
  ts: string;
  p50: number;
  p95: number;
  p99: number;
}

export interface GroupedCount {
  name: string;
  count: number;
  error_count: number;
  avg_latency_ms: number;
  error_rate: number;
  total_cost_usd: number;
  total_tokens: number;
}

export interface MonitoringTraces {
  trace_counts: TimeSeriesPoint[];
  error_counts: TimeSeriesPoint[];
  error_rate: TimeSeriesPoint[];
  latency_percentiles: LatencyPercentilesPoint[];
}

export interface MonitoringLLM {
  call_counts: TimeSeriesPoint[];
  error_counts: TimeSeriesPoint[];
  latency_percentiles: LatencyPercentilesPoint[];
}

export interface MonitoringCostTokens {
  total_cost: TimeSeriesPoint[];
  cost_per_trace: TimeSeriesPoint[];
  input_tokens: TimeSeriesPoint[];
  output_tokens: TimeSeriesPoint[];
  input_tokens_per_trace: TimeSeriesPoint[];
  output_tokens_per_trace: TimeSeriesPoint[];
}

export interface MonitoringTools {
  by_tool: GroupedCount[];
  tool_counts: TimeSeriesPoint[];
}

export interface MonitoringRunTypes {
  by_name: GroupedCount[];
}

export function fetchMonitoringTraces(hours = 168): Promise<MonitoringTraces> {
  return request<MonitoringTraces>(`/monitoring/traces?hours=${hours}`);
}

export function fetchMonitoringLLM(hours = 168): Promise<MonitoringLLM> {
  return request<MonitoringLLM>(`/monitoring/llm?hours=${hours}`);
}

export function fetchMonitoringCostTokens(hours = 168): Promise<MonitoringCostTokens> {
  return request<MonitoringCostTokens>(`/monitoring/cost-tokens?hours=${hours}`);
}

export function fetchMonitoringTools(hours = 168): Promise<MonitoringTools> {
  return request<MonitoringTools>(`/monitoring/tools?hours=${hours}`);
}

export function fetchMonitoringRunTypes(hours = 168): Promise<MonitoringRunTypes> {
  return request<MonitoringRunTypes>(`/monitoring/run-types?hours=${hours}`);
}

// ---------------------------------------------------------------------------
// Bulk CSV/JSONL Import
// ---------------------------------------------------------------------------

export function importExamples(
  datasetId: string,
  file: File,
  split: string = 'train',
): Promise<{ imported: number; total_rows: number }> {
  const form = new FormData();
  form.append('file', file);
  // For file uploads we must not set Content-Type (browser sets it with boundary)
  const apiKey = getStoredApiKey();
  const workspace = getCurrentWorkspace();
  const headers: Record<string, string> = {
    'X-VerdictLens-Workspace': workspace,
  };
  if (apiKey) {
    headers['X-VerdictLens-Key'] = apiKey;
  }
  const url = `${BASE}/datasets/${encodeURIComponent(datasetId)}/import?split=${encodeURIComponent(split)}`;
  return fetch(url, { method: 'POST', headers, body: form }).then(async (res) => {
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(`API ${res.status}: ${text.slice(0, 256)}`);
    }
    return res.json() as Promise<{ imported: number; total_rows: number }>;
  });
}

// ---------------------------------------------------------------------------
// Online Eval Rules
// ---------------------------------------------------------------------------

export interface OnlineEvalRule {
  rule_id: string;
  name: string;
  dataset_id: string;
  workspace_id: string;
  scorer_config: ScorerConfig[];
  filter_name?: string | null;
  enabled: boolean;
  created_at: string;
  last_fired?: string | null;
}

export interface OnlineEvalRuleInput {
  name: string;
  dataset_id: string;
  scorers: ScorerConfig[];
  filter_name?: string;
}

export function fetchOnlineEvalRules(): Promise<OnlineEvalRule[]> {
  return request<OnlineEvalRule[]>('/online-evals');
}

export function createOnlineEvalRule(body: OnlineEvalRuleInput): Promise<OnlineEvalRule> {
  return request<OnlineEvalRule>('/online-evals', { method: 'POST', body: JSON.stringify(body) });
}

export function deleteOnlineEvalRule(ruleId: string): Promise<{ status: string }> {
  return request<{ status: string }>(`/online-evals/${ruleId}`, { method: 'DELETE' });
}

// ---------------------------------------------------------------------------
// Human Annotations
// ---------------------------------------------------------------------------

export interface Annotation {
  id: string;
  trace_id: string;
  span_id?: string | null;
  workspace_id: string;
  thumbs?: 'up' | 'down' | null;
  label?: string | null;
  note?: string | null;
  created_at: string;
}

export function fetchAnnotations(traceId: string): Promise<Annotation[]> {
  return request<Annotation[]>(`/traces/${encodeURIComponent(traceId)}/annotations`);
}

export function createAnnotation(
  traceId: string,
  body: { span_id?: string; thumbs?: 'up' | 'down'; label?: string; note?: string },
): Promise<Annotation> {
  return request<Annotation>(`/traces/${encodeURIComponent(traceId)}/annotations`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function deleteAnnotation(annotationId: string): Promise<void> {
  return request<void>(`/annotations/${encodeURIComponent(annotationId)}`, { method: 'DELETE' });
}
