import { describe, expect, it } from "vitest";

import { SseParser } from "./sse";

describe("SSE parser", () => {
  it("reassembles frames split across network chunks", () => {
    const parser = new SseParser();
    expect(parser.push('event: TASK_COMPLETED\ndata: {"sequence":')).toEqual([]);
    expect(parser.push('1}\n')).toEqual([]);
    expect(parser.push('\n')).toEqual([
      { event: "TASK_COMPLETED", data: '{"sequence":1}' },
    ]);
  });

  it("ignores heartbeat comments and parses multiple frames", () => {
    const parser = new SseParser();
    expect(parser.push(': heartbeat\n\nevent: harness.control\ndata: {"kind":"GATEWAY_STATUS"}\n\ndata: {}\n\n')).toEqual([
      { event: "harness.control", data: '{"kind":"GATEWAY_STATUS"}' },
      { event: null, data: '{}' },
    ]);
  });

  it("supports CRLF and multiline data", () => {
    const parser = new SseParser();
    expect(parser.push('event: message\r\ndata: first\r\ndata: second\r\n\r\n')).toEqual([
      { event: "message", data: "first\nsecond" },
    ]);
  });
});
