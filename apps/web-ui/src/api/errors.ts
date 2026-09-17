import { ApiError } from "./client";
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError && [401, 403].includes(error.status)) {
    return `Permission denied. Configure a valid API token or ask the workspace administrator for access. ${error.message}`;
  }
  return error instanceof Error ? error.message : String(error);
}
