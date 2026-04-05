import { useState } from 'react';
import { ChevronRight, ChevronDown } from 'lucide-react';

interface Props {
  data: unknown;
  label?: string;
  defaultOpen?: boolean;
}

export default function JsonViewer({ data, label, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen);

  if (data === null || data === undefined) {
    return <span className="text-text-muted italic text-xs">null</span>;
  }

  if (typeof data === 'string') {
    const display = data.length > 300 ? data.slice(0, 300) + '…' : data;
    return <span className="text-xs break-all font-mono" style={{ color: 'var(--syntax-string)' }}>"{display}"</span>;
  }

  if (typeof data === 'number' || typeof data === 'boolean') {
    return <span className="text-xs font-mono" style={{ color: 'var(--syntax-number)' }}>{String(data)}</span>;
  }

  if (typeof data === 'object') {
    const isArray = Array.isArray(data);
    const entries = isArray
      ? (data as unknown[]).map((v, i) => [String(i), v] as const)
      : Object.entries(data as Record<string, unknown>);
    const bracket = isArray ? ['[', ']'] : ['{', '}'];

    if (entries.length === 0) {
      return <span className="text-text-muted text-xs">{bracket[0]}{bracket[1]}</span>;
    }

    return (
      <div className="text-xs font-mono">
        <button
          onClick={() => setOpen(!open)}
          className="inline-flex items-center gap-0.5 text-text-secondary hover:text-text-primary"
        >
          {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          {label && <span className="mr-1" style={{ color: 'var(--syntax-key)' }}>{label}:</span>}
          <span className="text-text-muted">
            {bracket[0]}{!open && `…${entries.length} items`}{!open && bracket[1]}
          </span>
        </button>
        {open && (
          <div className="ml-4 border-l border-border pl-3 mt-0.5 space-y-0.5">
            {entries.map(([key, val]) => (
              <div key={key}>
                <JsonViewer data={val} label={isArray ? undefined : key} defaultOpen={false} />
              </div>
            ))}
            <span className="text-text-muted">{bracket[1]}</span>
          </div>
        )}
      </div>
    );
  }

  return <span className="text-text-muted text-xs">{String(data)}</span>;
}
