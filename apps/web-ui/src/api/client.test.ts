// Unit tests for API client helpers (pure logic, node environment).
import { describe, expect, it } from "vitest";

import { parseMcpArgs } from "./client";

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
