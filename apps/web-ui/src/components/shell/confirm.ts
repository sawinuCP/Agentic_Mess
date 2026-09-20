// Promise-based confirmation primitive (UI1): replaces window.confirm for
// newly implemented UI. Mount one ConfirmHost (Confirm.tsx) in App; callers
// await confirmAction(). No store involvement — transient UI only.

export interface ConfirmOptions {
  title: string;
  body?: string;
  confirmLabel?: string;
  danger?: boolean;
}

type Resolver = (value: boolean) => void;

interface PendingRequest {
  options: ConfirmOptions;
  resolve: Resolver;
}

let pending: PendingRequest | null = null;
const listeners = new Set<() => void>();

export function getPendingConfirm(): PendingRequest | null {
  return pending;
}

export function confirmAction(options: ConfirmOptions): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    pending = { options, resolve };
    for (const listener of listeners) listener();
  });
}

export function settleConfirm(value: boolean): void {
  pending?.resolve(value);
  pending = null;
  for (const listener of listeners) listener();
}

export function subscribeConfirm(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
