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

export function getLiveness(): Promise<Liveness> {
  return getJson<Liveness>("/api/healthz");
}

export function getReadiness(): Promise<Readiness> {
  return getJson<Readiness>("/api/readyz");
}
