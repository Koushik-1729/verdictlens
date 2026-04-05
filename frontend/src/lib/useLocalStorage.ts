import { useEffect, useState } from 'react';

type SetValue<T> = T | ((current: T) => T);

export function useLocalStorage<T>(key: string, initialValue: T) {
  const [value, setValue] = useState<T>(() => {
    if (typeof window === 'undefined') return initialValue;
    try {
      const stored = localStorage.getItem(key);
      return stored != null ? (JSON.parse(stored) as T) : initialValue;
    } catch {
      return initialValue;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // Ignore storage write failures and keep UI functional.
    }
  }, [key, value]);

  function updateValue(nextValue: SetValue<T>) {
    setValue((current) =>
      typeof nextValue === 'function'
        ? (nextValue as (current: T) => T)(current)
        : nextValue
    );
  }

  return [value, updateValue] as const;
}
