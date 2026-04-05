import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { Lock, LogOut, AlertCircle } from 'lucide-react';
import { getStoredApiKey, setStoredApiKey, clearStoredApiKey } from '../lib/api';

interface Props {
  children: ReactNode;
}

export default function AuthGate({ children }: Props) {
  const [showPrompt, setShowPrompt] = useState(false);
  const [keyInput, setKeyInput] = useState('');
  const [error, setError] = useState('');
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    const handler = () => {
      setShowPrompt(true);
      setError('Invalid or missing API key');
    };
    window.addEventListener('verdictlens:auth-required', handler);
    return () => window.removeEventListener('verdictlens:auth-required', handler);
  }, []);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      const key = keyInput.trim();
      if (!key) return;

      setTesting(true);
      setError('');

      try {
        const base = import.meta.env.VITE_API_URL ?? '/api';
        const res = await fetch(`${base}/metrics?hours=1`, {
          headers: { 'X-VerdictLens-Key': key },
        });

        if (res.status === 401) {
          setError('Incorrect API key');
          setTesting(false);
          return;
        }

        setStoredApiKey(key);
        setShowPrompt(false);
        setKeyInput('');
        setError('');
        window.location.reload();
      } catch {
        setError('Cannot reach API server');
      } finally {
        setTesting(false);
      }
    },
    [keyInput],
  );

  const handleLogout = useCallback(() => {
    clearStoredApiKey();
    window.location.reload();
  }, []);

  const hasKey = !!getStoredApiKey();

  if (!showPrompt) {
    return (
      <>
        {children}
        {hasKey && <LogoutButton onClick={handleLogout} />}
      </>
    );
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-surface-900">
      <div className="w-full max-w-sm mx-4">
        <div className="bg-surface-800 border border-border rounded-xl shadow-2xl overflow-hidden">
          <div className="px-6 pt-8 pb-4 text-center">
            <div className="w-12 h-12 rounded-xl bg-accent/10 border border-accent/20 flex items-center justify-center mx-auto mb-4">
              <Lock className="h-5 w-5 text-accent" />
            </div>
            <h1 className="text-base font-semibold text-text-primary">VerdictLens</h1>
            <p className="text-xs text-text-muted mt-1">
              This instance requires an API key to access.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="px-6 pb-6 space-y-3">
            {error && (
              <div className="flex items-center gap-2 px-3 py-2 rounded-md bg-danger/10 border border-danger/20">
                <AlertCircle className="h-3.5 w-3.5 text-danger shrink-0" />
                <span className="text-xs text-danger">{error}</span>
              </div>
            )}

            <div>
              <label htmlFor="api-key" className="block text-xs font-medium text-text-secondary mb-1.5">
                API Key
              </label>
              <input
                id="api-key"
                type="password"
                value={keyInput}
                onChange={(e) => setKeyInput(e.target.value)}
                placeholder="Enter your VERDICTLENS_API_KEY"
                autoFocus
                className="w-full px-3 py-2 rounded-lg bg-surface-700 border border-border text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-accent/50 focus:border-accent transition-colors"
              />
            </div>

            <button
              type="submit"
              disabled={!keyInput.trim() || testing}
              className="w-full py-2 rounded-lg bg-accent text-white text-sm font-medium hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {testing ? 'Verifying...' : 'Authenticate'}
            </button>

            <p className="text-[10px] text-text-muted text-center leading-relaxed">
              The API key is set via <code className="font-mono bg-surface-700 px-1 rounded">VERDICTLENS_API_KEY</code> in your <code className="font-mono bg-surface-700 px-1 rounded">.env</code> file.
            </p>
          </form>
        </div>
      </div>
    </div>
  );
}

function LogoutButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      title="Clear API key"
      className="fixed bottom-4 right-4 z-50 p-2 rounded-lg bg-surface-800 border border-border text-text-muted hover:text-text-primary hover:border-border/80 transition-colors shadow-lg"
    >
      <LogOut className="h-3.5 w-3.5" />
    </button>
  );
}
