import { useEffect, useMemo, useState } from 'react';
import clsx from 'clsx';
import {
  Building2,
  Check,
  Copy,
  Eye,
  EyeOff,
  Key,
  Loader2,
  Plus,
  Search,
  Trash2,
  X,
} from 'lucide-react';
import EmptyState from '../components/EmptyState';
import { Badge, OutlineButton, PrimaryButton } from '../components/ui';
import {
  createApiKey,
  createWorkspace,
  deleteApiKey,
  fetchApiKeys,
  fetchWorkspaces,
  getCurrentWorkspace,
  setCurrentWorkspace,
  type ApiKey,
  type Workspace,
} from '../lib/api';
import { timeAgo } from '../lib/utils';

const WORKSPACE_GRID = 'grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_140px_120px_48px]';

export default function WorkspaceSettings() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedWs, setSelectedWs] = useState<string | null>(null);
  const [apiKeys, setApiKeys] = useState<ApiKey[]>([]);
  const [keysLoading, setKeysLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [activeWorkspaceSlug, setActiveWorkspaceSlug] = useState(getCurrentWorkspace());

  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState('');
  const [newSlug, setNewSlug] = useState('');
  const [creating, setCreating] = useState(false);

  const [showKeyForm, setShowKeyForm] = useState(false);
  const [keyName, setKeyName] = useState('');
  const [creatingKey, setCreatingKey] = useState(false);
  const [newKeyValue, setNewKeyValue] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [showKey, setShowKey] = useState(false);

  useEffect(() => {
    fetchWorkspaces()
      .then((loadedWorkspaces) => {
        setWorkspaces(loadedWorkspaces);
        if (loadedWorkspaces.length === 0) return;

        const current = loadedWorkspaces.find((workspace) => workspace.slug === getCurrentWorkspace()) ?? loadedWorkspaces[0];
        void selectWorkspace(current.id);
      })
      .finally(() => setLoading(false));
  }, []);

  async function selectWorkspace(id: string) {
    setSelectedWs(id);
    setKeysLoading(true);
    setNewKeyValue(null);
    try {
      const keys = await fetchApiKeys(id);
      setApiKeys(keys);
    } catch {
      setApiKeys([]);
    } finally {
      setKeysLoading(false);
    }
  }

  async function handleCreateWorkspace() {
    if (!newName.trim() || !newSlug.trim()) return;
    setCreating(true);
    try {
      const created = await createWorkspace({
        name: newName.trim(),
        slug: newSlug.trim(),
      });
      setWorkspaces((prev) => [created, ...prev]);
      setShowCreate(false);
      setNewName('');
      setNewSlug('');
      await selectWorkspace(created.id);
    } finally {
      setCreating(false);
    }
  }

  async function handleCreateKey() {
    if (!selectedWs || !keyName.trim()) return;
    setCreatingKey(true);
    try {
      const created = await createApiKey(selectedWs, { name: keyName.trim() });
      setApiKeys((prev) => [created, ...prev]);
      setNewKeyValue(created.key ?? null);
      setShowKeyForm(false);
      setKeyName('');
      setShowKey(true);
    } finally {
      setCreatingKey(false);
    }
  }

  async function handleDeleteKey(keyId: string) {
    if (!selectedWs || !confirm('Delete this API key? This cannot be undone.')) return;
    await deleteApiKey(selectedWs, keyId);
    setApiKeys((prev) => prev.filter((key) => key.id !== keyId));
  }

  function copyToClipboard(text: string) {
    void navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  function makeWorkspaceActive(workspace: Workspace) {
    setCurrentWorkspace(workspace.slug);
    setActiveWorkspaceSlug(workspace.slug);
  }

  const filteredWorkspaces = useMemo(
    () =>
      workspaces.filter((workspace) => {
        if (!search) return true;
        const query = search.toLowerCase();
        return workspace.name.toLowerCase().includes(query) || workspace.slug.toLowerCase().includes(query);
      }),
    [search, workspaces],
  );

  const selectedWorkspace = workspaces.find((workspace) => workspace.id === selectedWs) ?? null;
  const activeWorkspace = workspaces.find((workspace) => workspace.slug === activeWorkspaceSlug) ?? null;

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-[rgb(var(--border))] px-6 py-3.5">
        <h1 className="text-[15px] font-semibold text-text-primary">Workspaces</h1>
        <PrimaryButton onClick={() => setShowCreate(true)}>
          <Plus className="h-3.5 w-3.5" />
          New Workspace
        </PrimaryButton>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {selectedWorkspace ? (
            <OutlineButton onClick={() => makeWorkspaceActive(selectedWorkspace)}>
              <Check className="h-3.5 w-3.5" />
              Use {selectedWorkspace.slug}
            </OutlineButton>
          ) : null}
        </div>
        <div className="flex items-center rounded-md border border-[rgb(var(--border))] bg-[rgb(var(--surface-800))] px-3">
          <Search className="h-3.5 w-3.5 text-text-muted" />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search workspaces..."
            className="h-8 w-64 border-0 bg-transparent px-2 text-[13px] text-text-primary placeholder:text-text-muted focus:outline-none"
          />
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <StatCard label="Workspaces" value={String(workspaces.length)} />
        <StatCard label="API Keys" value={String(apiKeys.length)} />
        <StatCard label="Active Workspace" value={activeWorkspace?.slug ?? 'default'} mono />
        <StatCard label="Selected Keys" value={selectedWorkspace ? String(apiKeys.length) : '0'} />
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-6 w-6 animate-spin text-text-muted" />
        </div>
      ) : filteredWorkspaces.length === 0 ? (
        <EmptyState
          icon={<Building2 className="h-5 w-5" />}
          title={workspaces.length === 0 ? 'No workspaces yet' : 'No matching workspaces'}
          description={
            workspaces.length === 0
              ? 'Create a workspace to isolate traces, datasets, evaluations, and API keys.'
              : 'Try a different search query or create a new workspace.'
          }
          action={
            <PrimaryButton onClick={() => setShowCreate(true)}>
              <Plus className="h-3.5 w-3.5" />
              Create Workspace
            </PrimaryButton>
          }
        />
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_420px]">
          <div className="table-shell">
            <div className={clsx('table-header', WORKSPACE_GRID)}>
              <span>Workspace</span>
              <span>Description</span>
              <span>Created</span>
              <span>Status</span>
              <span />
            </div>

            <div>
              {filteredWorkspaces.map((workspace) => {
                const isSelected = selectedWs === workspace.id;
                const isActive = activeWorkspaceSlug === workspace.slug;
                return (
                  <button
                    key={workspace.id}
                    onClick={() => void selectWorkspace(workspace.id)}
                    className={clsx(
                      'data-row min-h-[72px] w-full items-center text-left transition-all duration-100',
                      WORKSPACE_GRID,
                      isSelected ? 'bg-accent/[0.08] ring-1 ring-inset ring-accent/20' : 'hover:bg-accent/[0.04]',
                    )}
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <Building2 className="h-4 w-4 shrink-0 text-text-muted" />
                        <span className="truncate text-[14px] font-semibold text-text-primary">{workspace.name}</span>
                        {isActive ? <Badge className="rounded-full px-2.5 py-1">active</Badge> : null}
                      </div>
                      <div className="mt-1 font-mono text-[11px] text-text-muted">{workspace.slug}</div>
                    </div>

                    <div className="min-w-0 text-[13px] text-text-secondary">
                      <span className="block truncate">{workspace.description || 'No description provided'}</span>
                    </div>

                    <div className="text-[12px] text-text-muted">{timeAgo(workspace.created_at)}</div>

                    <div>
                      <span
                        className={clsx(
                          'inline-flex rounded-full px-2.5 py-1 text-[11px] font-medium',
                          isActive ? 'bg-accent/10 text-accent' : 'bg-surface-800 text-text-secondary',
                        )}
                      >
                        {isActive ? 'Current' : 'Available'}
                      </span>
                    </div>

                    <div className="flex justify-end">
                      <button
                        onClick={(event) => {
                          event.stopPropagation();
                          makeWorkspaceActive(workspace);
                        }}
                        className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-accent/5 hover:text-accent"
                        title="Use workspace"
                      >
                        <Check className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="ui-card overflow-hidden">
            {!selectedWorkspace ? (
              <div className="flex items-center justify-center py-20 text-sm text-text-muted">
                Select a workspace to view keys and configuration.
              </div>
            ) : keysLoading ? (
              <div className="flex items-center justify-center py-20">
                <Loader2 className="h-5 w-5 animate-spin text-text-muted" />
              </div>
            ) : (
              <div>
                <div className="flex items-start justify-between border-b border-border px-5 py-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <div className="text-[16px] font-semibold text-text-primary">{selectedWorkspace.name}</div>
                      {activeWorkspaceSlug === selectedWorkspace.slug ? (
                        <Badge className="rounded-full px-2.5 py-1">current workspace</Badge>
                      ) : null}
                    </div>
                    <div className="mt-1 font-mono text-[12px] text-text-secondary">{selectedWorkspace.slug}</div>
                  </div>
                  <PrimaryButton onClick={() => setShowKeyForm(true)}>
                    <Key className="h-3.5 w-3.5" />
                    New Key
                  </PrimaryButton>
                </div>

                {newKeyValue ? (
                  <div className="border-b border-success/20 bg-success/5 px-5 py-4">
                    <div className="text-[12px] font-medium text-success">
                      API key created. Copy it now, it will not be shown again.
                    </div>
                    <div className="mt-3 flex items-center gap-2">
                      <code className="flex-1 overflow-auto rounded-md bg-surface-800 px-3 py-2 text-[12px] font-mono text-text-primary">
                        {showKey ? newKeyValue : '•'.repeat(48)}
                      </code>
                      <button
                        onClick={() => setShowKey((value) => !value)}
                        className="rounded-md p-2 text-text-muted transition-colors hover:bg-surface-800 hover:text-text-primary"
                      >
                        {showKey ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                      </button>
                      <button
                        onClick={() => copyToClipboard(newKeyValue)}
                        className="rounded-md p-2 text-text-muted transition-colors hover:bg-surface-800 hover:text-text-primary"
                      >
                        {copied ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />}
                      </button>
                    </div>
                  </div>
                ) : null}

                {showKeyForm ? (
                  <div className="border-b border-border px-5 py-4">
                    <div className="space-y-3">
                      <div className="text-[13px] font-medium text-text-primary">Create API key</div>
                      <input
                        value={keyName}
                        onChange={(event) => setKeyName(event.target.value)}
                        placeholder="CI/CD, local dev, staging runner..."
                        className="input-base w-full text-[13px]"
                        autoFocus
                      />
                      <div className="flex items-center justify-end gap-2">
                        <OutlineButton onClick={() => setShowKeyForm(false)}>Cancel</OutlineButton>
                        <PrimaryButton onClick={handleCreateKey} disabled={creatingKey || !keyName.trim()}>
                          {creatingKey ? 'Creating…' : 'Create Key'}
                        </PrimaryButton>
                      </div>
                    </div>
                  </div>
                ) : null}

                {apiKeys.length === 0 && !showKeyForm ? (
                  <div className="px-5 py-14 text-center">
                    <Key className="mx-auto h-8 w-8 text-text-muted opacity-40" />
                    <div className="mt-3 text-[15px] font-semibold text-text-primary">No API keys yet</div>
                    <div className="mt-1 text-[13px] text-text-secondary">
                      Create a key to send SDK traces into this workspace.
                    </div>
                  </div>
                ) : (
                  <div className="table-shell border-x-0 border-t-0 rounded-none">
                    <div className="table-header grid-cols-[minmax(0,1fr)_120px_48px]">
                      <span>Key</span>
                      <span>Created</span>
                      <span />
                    </div>
                    <div>
                      {apiKeys.map((key) => (
                        <div key={key.id} className="data-row grid-cols-[minmax(0,1fr)_120px_48px] text-[12px]">
                          <div className="min-w-0">
                            <div className="text-[13px] font-medium text-text-primary">{key.name}</div>
                            <div className="mt-1 font-mono text-[11px] text-text-muted">{key.key_prefix}</div>
                          </div>
                          <div className="text-text-muted">{timeAgo(key.created_at)}</div>
                          <div className="flex justify-end">
                            <button
                              onClick={() => void handleDeleteKey(key.id)}
                              className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-danger/5 hover:text-danger"
                              title="Delete key"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div className="border-t border-border px-5 py-4">
                  <div className="text-[11px] font-medium uppercase tracking-wider text-text-muted">SDK Configuration</div>
                  <pre className="mt-2 overflow-auto rounded-md bg-surface-800 p-3 text-[12px] font-mono text-text-secondary">
{`from agentlens import configure

configure(
    api_key="al_...",
    workspace="${selectedWorkspace.slug}",
    project="my-project",
    base_url="http://localhost:8000",
)`}
                  </pre>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {showCreate ? (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/35 p-4 backdrop-blur-[2px]">
          <div className="w-full max-w-lg overflow-hidden rounded-2xl border border-border bg-surface-900 shadow-[0_20px_80px_rgba(15,23,42,0.12)]">
            <div className="flex items-start justify-between border-b border-border px-5 py-4">
              <div>
                <div className="text-[20px] font-semibold text-text-primary">Create Workspace</div>
                <div className="mt-1 text-[13px] text-text-secondary">
                  Set up an isolated workspace for traces, evaluations, prompts, and API keys.
                </div>
              </div>
              <button
                onClick={() => setShowCreate(false)}
                className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-surface-800 hover:text-text-primary"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="space-y-4 px-5 py-5">
              <div className="space-y-1.5">
                <label className="text-[12px] font-medium uppercase tracking-wider text-text-muted">Workspace Name</label>
                <input
                  value={newName}
                  onChange={(event) => {
                    const value = event.target.value;
                    setNewName(value);
                    setNewSlug(
                      value
                        .toLowerCase()
                        .trim()
                        .replace(/[^a-z0-9-]/g, '-')
                        .replace(/-+/g, '-')
                        .replace(/^-|-$/g, ''),
                    );
                  }}
                  placeholder="Customer support"
                  className="input-base w-full text-[13px]"
                  autoFocus
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-[12px] font-medium uppercase tracking-wider text-text-muted">Slug</label>
                <input
                  value={newSlug}
                  onChange={(event) => setNewSlug(event.target.value)}
                  placeholder="customer-support"
                  className="input-base w-full font-mono text-[13px]"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-4">
              <OutlineButton onClick={() => setShowCreate(false)}>Cancel</OutlineButton>
              <PrimaryButton onClick={handleCreateWorkspace} disabled={creating || !newName.trim() || !newSlug.trim()}>
                {creating ? 'Creating…' : 'Create Workspace'}
              </PrimaryButton>
            </div>
          </div>
        </div>
      ) : null}
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="ui-card px-5 py-4">
      <div className="text-[12px] font-medium text-text-muted">{label}</div>
      <div className={clsx('mt-1 text-[24px] font-semibold text-text-primary', mono && 'font-mono text-[20px]')}>
        {value}
      </div>
    </div>
  );
}
