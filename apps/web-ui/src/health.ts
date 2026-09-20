export interface ComponentHealth {
  status: string;
  detail: string | null;
}

export interface Liveness {
  status: string;
  version: string;
  environment: string;
}

export interface Readiness {
  ready: boolean;
  version: string;
  environment: string;
  checks: Record<string, ComponentHealth>;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`${path} -> HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

// Liveness/readiness live at the server ROOT (/healthz, /readyz) — not under
// /api (see backend PUBLIC_PATHS). Same-origin production resolves them
// directly; vite dev proxies them below.
export function getLiveness(): Promise<Liveness> {
  return getJson<Liveness>("/healthz");
}

export function getReadiness(): Promise<Readiness> {
  return getJson<Readiness>("/readyz");
}
