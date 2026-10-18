import { useEffect, useRef, useState } from 'react';
import { ApiError } from './client';

export interface Resource<T> {
  data: T | undefined;
  /** A request is in flight; `data` is still the previous answer, shown dimmed. */
  loading: boolean;
  error: string | null;
}

/**
 * Runs `load` whenever `key` changes and keeps the previous answer on screen while the next one
 * loads (no skeleton, no jump). A late answer of an older request is dropped.
 */
export function useResource<T>(
  key: string,
  load: (signal: AbortSignal) => Promise<T>,
  enabled = true,
): Resource<T> {
  const [state, setState] = useState<Resource<T>>({ data: undefined, loading: enabled, error: null });
  const loader = useRef(load);
  loader.current = load;

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    loader
      .current(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setState({ data, loading: false, error: null });
      })
      .catch((e: unknown) => {
        if (controller.signal.aborted) return;
        const message = e instanceof ApiError ? e.message : 'The request failed. Check the connection.';
        setState((s) => ({ ...s, loading: false, error: message }));
      });
    return () => controller.abort();
  }, [key, enabled]);

  return state;
}
