import { describe, expect, it } from "vitest";

import type { LeaseInfo, PortInfo } from "../../types";
import { summarizeRuntime } from "./runtime";

function port(overrides: Partial<PortInfo> = {}): PortInfo {
  return {
    id: "p1",
    port: 21001,
    purpose: "preview",
    holder: null,
    project_id: "p",
    ttl_seconds: 3600,
    allocated_at: "",
    expires_at: "",
    released_at: null,
    status: "active",
    ...overrides,
  };
}

function lease(overrides: Partial<LeaseInfo> = {}): LeaseInfo {
  return {
    id: "l1",
    kind: "port",
    key: "k",
    project_id: "p",
    holder_agent_id: null,
    holder_session: null,
    ttl_seconds: 300,
    acquired_at: "",
    expires_at: "",
    released_at: null,
    status: "active",
    ...overrides,
  };
}

describe("summarizeRuntime", () => {
  it("counts by status across ports and leases", () => {
    const summary = summarizeRuntime(
      [port(), port({ id: "p2", status: "expired" }), port({ id: "p3", status: "released" })],
      [lease(), lease({ id: "l2", status: "expired" })],
    );
    expect(summary).toEqual({
      portsTotal: 3,
      portsActive: 1,
      portsExpired: 1,
      leasesTotal: 2,
      leasesActive: 1,
      leasesExpired: 1,
    });
  });

  it("handles empty state", () => {
    expect(summarizeRuntime([], [])).toEqual({
      portsTotal: 0,
      portsActive: 0,
      portsExpired: 0,
      leasesTotal: 0,
      leasesActive: 0,
      leasesExpired: 0,
    });
  });
});
