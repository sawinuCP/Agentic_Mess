// Unit tests for investigation explanations (UI-5 §8; deterministic, no invention).
import { describe, expect, it } from "vitest";

import type { TaskInfo } from "../types";
import { attemptRows, whyRequirement } from "./explain";
import { task as makeTask, requirement as makeRequirement, agent as makeAgent } from "./testFixtures";

describe("whyRequirement", () => {
  const verifiedReq = makeRequirement({
    status: "VERIFIED",
    criteria: [{
      id: "c1",
      description: "EPF calculation",
      kind: "command",
      mandatory: true,
      state: "verified",
      verification: {
        validation_id: "v1",
        verified_at: "2026-09-21T10:00:00Z",
        status: "passed",
        evidence_artifact_id: "art9",
        task_id: "t1",
        source_head_sha: "abc123",
        source_branch: "main",
        source_dirty: false,
      },
    }],
  });
  const tasks: TaskInfo[] = [makeTask({
    status: "completed",
    attempts: [{
      attempt_number: 2, agent_id: "a1", outcome: "success",
      evidence_artifact_ids: ["art9"], failure_class: null, failure_detail: null,
    }],
  })];

  it("binds verified criteria to evidence, task, and latest success", () => {
    const out = whyRequirement(verifiedReq, tasks, [makeAgent()]);
    expect(out.verdict).toBe("VERIFIED");
    expect(out.chains).toHaveLength(1);
    const chain = out.chains[0];
    expect(chain.verifiedAt).toBe("2026-09-21T10:00:00Z");
    expect(chain.links.map((l) => l.kind)).toEqual(["evidence", "task", "attempt"]);
    expect(chain.links[0].nodeId).toBe("ev:art9");
    expect(chain.links[1].nodeId).toBe("task:t1");
    // Attempt line is the latest recorded success — labelled, never invented.
    expect(chain.links[2].label).toContain("latest recorded success");
    expect(chain.provenance?.source_head_sha).toBe("abc123");
  });

  it("reports missing evidence for UNKNOWN without manufacturing edges", () => {
    const out = whyRequirement(
      makeRequirement({ status: "UNKNOWN", criteria: [] }),
      [],
      [],
    );
    expect(out.verdict).toBe("UNKNOWN");
    expect(out.chains).toHaveLength(0);
    expect(out.missing.length).toBeGreaterThan(0);
  });

  it("lists failed mandatory criteria for FAILED", () => {
    const out = whyRequirement(
      makeRequirement({
        status: "FAILED",
        criteria: [{ id: "c9", description: "Broken", kind: "command", mandatory: true, state: "failed" }],
      }),
      [],
      [],
    );
    expect(out.verdict).toBe("FAILED");
    expect(out.failedCriteria).toEqual(["Broken"]);
  });

  it("omits links the backend never recorded", () => {
    const bare = makeRequirement({
      status: "VERIFIED",
      criteria: [{
        id: "c1", description: "Vague", kind: "manual", mandatory: true,
        state: "verified", verification: null,
      }],
    });
    const out = whyRequirement(bare, [], []);
    expect(out.chains).toHaveLength(1);
    expect(out.chains[0].links).toHaveLength(0);
    expect(out.chains[0].verifiedAt).toBeNull();
  });
});

describe("attemptRows", () => {
  it("distinguishes outcomes without inventing agents", () => {
    const rows = attemptRows(makeTask({
      attempts: [
        { attempt_number: 1, agent_id: "a1", outcome: "failed", evidence_artifact_ids: [], failure_class: "TIMEOUT", failure_detail: null },
        { attempt_number: 2, agent_id: null, outcome: null, evidence_artifact_ids: ["x"], failure_class: null, failure_detail: null },
      ],
    }), [makeAgent()]);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({ attemptNumber: 1, agent: "Backend", outcome: "failed", failure: "TIMEOUT", evidenceCount: 0 });
    expect(rows[1]).toMatchObject({ agent: "unassigned", outcome: "in progress", failure: null, evidenceCount: 1 });
  });
});
