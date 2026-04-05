import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

export function useKeyboardShortcuts() {
  const navigate = useNavigate();
  const [helpOpen, setHelpOpen] = useState(false);

  const handler = useCallback((e: KeyboardEvent) => {
    const target = e.target as HTMLElement;
    const tag = target.tagName.toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || target.isContentEditable) {
      return;
    }

    if (e.key === '?' && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      setHelpOpen((prev) => !prev);
      return;
    }

    if (e.key === 'Escape') {
      setHelpOpen(false);
      return;
    }

    if (e.key === '/' && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      const searchInput = document.querySelector<HTMLInputElement>('[data-search]');
      searchInput?.focus();
      return;
    }

    if (e.key === 'g' && !e.ctrlKey && !e.metaKey) {
      const next = (ev: KeyboardEvent) => {
        window.removeEventListener('keydown', next);
        const routes: Record<string, string> = {
          d: '/',
          t: '/traces',
          l: '/live',
          b: '/blame',
          r: '/replay',
          c: '/costs',
          a: '/alerts',
          s: '/settings',
        };
        if (routes[ev.key]) {
          ev.preventDefault();
          navigate(routes[ev.key]);
        }
      };
      window.addEventListener('keydown', next, { once: true });
      setTimeout(() => window.removeEventListener('keydown', next), 1500);
      return;
    }
  }, [navigate]);

  useEffect(() => {
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [handler]);

  return { helpOpen, setHelpOpen };
}

export const SHORTCUTS = [
  { keys: ['?'], description: 'Toggle this help' },
  { keys: ['/'], description: 'Focus search' },
  { keys: ['g', 'd'], description: 'Go to Dashboard' },
  { keys: ['g', 't'], description: 'Go to Traces' },
  { keys: ['g', 'l'], description: 'Go to Live Feed' },
  { keys: ['g', 'b'], description: 'Go to Blame' },
  { keys: ['g', 'r'], description: 'Go to Replay' },
  { keys: ['g', 'c'], description: 'Go to Cost Explorer' },
  { keys: ['g', 'a'], description: 'Go to Alerts' },
  { keys: ['g', 's'], description: 'Go to Settings' },
  { keys: ['Esc'], description: 'Close modal / dialog' },
];
