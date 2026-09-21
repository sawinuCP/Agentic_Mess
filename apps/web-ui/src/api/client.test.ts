// Unit tests for API client helpers (pure logic, node environment).
import { afterEach, describe, expect, it, vi } from "vitest";

import { parseMcpArgs, verifyCriterion } from "./client";

describe("parseMcpArgs", () => {
  it("accepts empty input as empty arguments", () => {
    expect(parseMcpArgs("")).toEqual({ ok: true, value: {} });
    expect(parseMcpArgs("   ")).toEqual({ ok: true, value: {} });
  });

  it("parses JSON objects without evaluating them", () => {
    expect(parseMcpArgs('{"path": "x", "n": 2}')).toEqual({
      ok: true,
      value: { path: "x", n: 2 },
    });
  });

  it("rejects non-objects and malformed JSON with reasons", () => {
    expect(parseMcpArgs("[1, 2]").ok).toBe(false);
    expect(parseMcpArgs('"str"').ok).toBe(false);
    expect(parseMcpArgs("42").ok).toBe(false);
    const bad = parseMcpArgs("{oops");
    expect(bad.ok).toBe(false);
    if (!bad.ok) expect(bad.error).toContain("valid JSON");
  });
});

describe("verifyCriterion", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts evidence to the criterion verify endpoint", async () => {
    const seen: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      seen.push({ url, init });
      return new Response(
        JSON.stringify({ criterion_id: "c", state: "verified", validation_id: "v", evidence_artifact_id: "a" }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    });
    const result = await verifyCriterion("req-1", "crit-9", { evidence_artifact_id: "art-2", task_id: null });
    expect(seen).toHaveLength(1);
    expect(seen[0].url).toBe("/api/requirements/req-1/criteria/crit-9/verify");
    expect(seen[0].init?.method).toBe("POST");
    expect(JSON.parse(String(seen[0].init?.body)).evidence_artifact_id).toBe("art-2");
    expect(result.state).toBe("verified");
  });
});
