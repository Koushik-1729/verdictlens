import { X } from 'lucide-react';
import { SHORTCUTS } from '../lib/useKeyboardShortcuts';

interface Props {
  onClose: () => void;
}

export default function KeyboardShortcutsModal({ onClose }: Props) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="bg-surface-900 border border-border rounded-xl shadow-2xl w-full max-w-sm"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <h2 className="text-sm font-semibold text-text-primary">Keyboard Shortcuts</h2>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary transition-colors">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-4 space-y-1.5 max-h-[60vh] overflow-y-auto">
          {SHORTCUTS.map((s, i) => (
            <div key={i} className="flex items-center justify-between py-1.5">
              <span className="text-xs text-text-secondary">{s.description}</span>
              <div className="flex items-center gap-1">
                {s.keys.map((key, j) => (
                  <span key={j}>
                    {j > 0 && <span className="text-text-muted text-[10px] mx-0.5">then</span>}
                    <kbd className="inline-block min-w-[22px] text-center text-[11px] font-mono text-text-primary bg-surface-700 border border-border rounded px-1.5 py-0.5">
                      {key}
                    </kbd>
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div className="px-5 py-3 border-t border-border">
          <p className="text-[10px] text-text-muted text-center">
            Press <kbd className="text-[10px] font-mono bg-surface-700 border border-border rounded px-1 py-0.5">?</kbd> to toggle
          </p>
        </div>
      </div>
    </div>
  );
}
