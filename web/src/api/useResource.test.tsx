import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ApiError } from './client';
import { useResource } from './useResource';

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe('useResource', () => {
  it('keeps the previous answer on screen while the next one loads', async () => {
    const first = deferred<string>();
    const second = deferred<string>();
    const { result, rerender } = renderHook(({ id, d }) => useResource(id, () => d.promise), {
      initialProps: { id: 'a', d: first },
    });
    expect(result.current).toEqual({ data: undefined, loading: true, error: null });
    await act(async () => first.resolve('one'));
    expect(result.current).toEqual({ data: 'one', loading: false, error: null });

    rerender({ id: 'b', d: second });
    await waitFor(() => expect(result.current.loading).toBe(true));
    expect(result.current.data).toBe('one'); // still there, to be shown dimmed
    await act(async () => second.resolve('two'));
    expect(result.current).toEqual({ data: 'two', loading: false, error: null });
  });

  it('drops the answer of a request that was replaced before it came back', async () => {
    const slow = deferred<string>();
    const fast = deferred<string>();
    const { result, rerender } = renderHook(({ id, d }) => useResource(id, () => d.promise), {
      initialProps: { id: 'a', d: slow },
    });
    rerender({ id: 'b', d: fast });
    await act(async () => fast.resolve('fast'));
    await act(async () => slow.resolve('slow'));
    expect(result.current.data).toBe('fast');
  });

  it('turns an API error into its message and any other failure into a plain one', async () => {
    const { result } = renderHook(() => useResource('x', () => Promise.reject(new ApiError(503, 'Not ready'))));
    await waitFor(() => expect(result.current.error).toBe('Not ready'));
    const other = renderHook(() => useResource('y', () => Promise.reject(new TypeError('Failed to fetch'))));
    await waitFor(() => expect(other.result.current.error).toMatch(/Check the connection/));
  });

  it('does nothing while it is disabled', async () => {
    let called = 0;
    renderHook(() => useResource('x', async () => (called += 1), false));
    await new Promise((r) => setTimeout(r, 20));
    expect(called).toBe(0);
  });
});
