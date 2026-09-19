import { describe, expect, it } from "vitest";

import { applyTheme, readTheme, xtermTheme } from "./theme";

describe("theme contract", () => {
  it("defaults to dark without storage", () => {
    // node has no localStorage: the guard path must still resolve dark.
    expect(readTheme()).toBe("dark");
  });

  it("maps terminal palettes per theme without sharing backgrounds", () => {
    const dark = xtermTheme("dark");
    const light = xtermTheme("light");
    expect(dark.background).not.toBe(light.background);
    expect(dark.foreground).not.toBe(light.foreground);
    for (const palette of [dark, light]) {
      expect(palette.background).toMatch(/^#[0-9a-f]{6}$/);
      expect(palette.foreground).toMatch(/^#[0-9a-f]{6}$/);
    }
  });

  it("applyTheme never throws without DOM or storage", () => {
    expect(() => applyTheme("light")).not.toThrow();
    expect(() => applyTheme("dark")).not.toThrow();
  });
});
