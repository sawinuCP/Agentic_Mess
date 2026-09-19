// Runtime resource summary (Wave 6): pure projection over port/lease lists.
//
// No React, no fetch — unit-testable in the node Vitest suite. The RuntimeView
// renders this; refresh comes from the existing list endpoints.

import type { LeaseInfo, PortInfo } from "../../types";

export interface RuntimeSummary {
  portsTotal: number;
  portsActive: number;
  portsExpired: number;
  leasesTotal: number;
  leasesActive: number;
  leasesExpired: number;
}

export function summarizeRuntime(ports: PortInfo[], leases: LeaseInfo[]): RuntimeSummary {
  const isActive = (status: string): boolean => status === "active";
  const isExpired = (status: string): boolean => status === "expired";
  return {
    portsTotal: ports.length,
    portsActive: ports.filter((p) => isActive(p.status)).length,
    portsExpired: ports.filter((p) => isExpired(p.status)).length,
    leasesTotal: leases.length,
    leasesActive: leases.filter((l) => isActive(l.status)).length,
    leasesExpired: leases.filter((l) => isExpired(l.status)).length,
  };
}
