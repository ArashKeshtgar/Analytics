import { config } from '../config';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

export type Params = Record<string, string | undefined>;

/** Something the client can call to get a token and to start over when the API refuses it. */
export interface Session {
  accessToken(): Promise<string | null>;
  /** The API said 401: the token is gone or expired. */
  expired(): void;
}

function messageFor(status: number, detail: string | undefined): string {
  if (status === 403) return 'You do not have permission to see this.';
  if (status === 503) return detail ?? 'The service is not ready yet.';
  return detail ?? `The request failed (${status}).`;
}

export function buildUrl(path: string, params: Params = {}): string {
  const query = new URLSearchParams();
  for (const [name, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') query.set(name, value);
  }
  const text = query.toString();
  return `${config.apiUrl}${path}${text ? `?${text}` : ''}`;
}

export async function apiGet<T>(
  session: Session,
  path: string,
  params: Params = {},
  signal?: AbortSignal,
): Promise<T> {
  const token = await session.accessToken();
  if (!token) {
    session.expired();
    throw new ApiError(401, 'Sign in again.');
  }
  const response = await fetch(buildUrl(path, params), {
    headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
    signal,
  });
  if (response.status === 401) {
    session.expired();
    throw new ApiError(401, 'Your session ended. Signing in again.');
  }
  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = (await response.json()) as { detail?: unknown };
      detail = typeof body.detail === 'string' ? body.detail : undefined;
    } catch {
      detail = undefined;
    }
    throw new ApiError(response.status, messageFor(response.status, detail));
  }
  return (await response.json()) as T;
}
