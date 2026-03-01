import { getAccessToken } from './auth';

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

/**
 * Returns an Authorization: Bearer <token> header object.
 * If no valid session exists (e.g., during initial load before Authenticator resolves),
 * returns an empty object. The Authenticator component will redirect to login,
 * and the backend will return 401.
 */
export async function authHeaders(): Promise<Record<string, string>> {
  try {
    const token = await getAccessToken();
    return { Authorization: `Bearer ${token}` };
  } catch {
    return {};
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const url = path.startsWith('http') ? path : `${BACKEND_URL}${path}`;
  const res = await fetch(url, { headers: await authHeaders() });
  if (res.status === 401) {
    if (typeof window !== 'undefined') {
      window.location.href = '/';
    }
    throw new Error('Session expired');
  }
  if (!res.ok) {
    const errorText = await res.text().catch(() => '');
    throw new Error(`API error ${res.status}: ${errorText || res.statusText}`);
  }
  return res.json();
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const url = path.startsWith('http') ? path : `${BACKEND_URL}${path}`;
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    body: JSON.stringify(body),
  });
  if (res.status === 401) {
    if (typeof window !== 'undefined') {
      window.location.href = '/';
    }
    throw new Error('Session expired');
  }
  if (!res.ok) {
    const errorText = await res.text().catch(() => '');
    throw new Error(`API error ${res.status}: ${errorText || res.statusText}`);
  }
  return res.json();
}

export async function apiDelete<T>(path: string): Promise<T> {
  const url = path.startsWith('http') ? path : `${BACKEND_URL}${path}`;
  const res = await fetch(url, {
    method: 'DELETE',
    headers: await authHeaders(),
  });
  if (res.status === 401) {
    if (typeof window !== 'undefined') {
      window.location.href = '/';
    }
    throw new Error('Session expired');
  }
  if (!res.ok) {
    const errorText = await res.text().catch(() => '');
    throw new Error(`API error ${res.status}: ${errorText || res.statusText}`);
  }
  return res.json();
}

export { BACKEND_URL };
