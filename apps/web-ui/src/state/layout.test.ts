import { afterEach, describe, expect, it, vi } from "vitest";
import { clampSize, defaultLayout, readLayout, saveLayout } from "./layout";
afterEach(() => vi.unstubAllGlobals());
describe("layout preferences", () => {
  it("clamps invalid and extreme dimensions", () => {
    expect(clampSize(NaN, 160, 600)).toBe(160);
    expect(clampSize(900, 160, 600)).toBe(600);
    expect(clampSize(20, 160, 600)).toBe(160);
  });
  it("works without browser storage", () => expect(readLayout()).toEqual(defaultLayout));
  it("persists only layout and restores it", () => {
    let saved = "";
    vi.stubGlobal("localStorage", { getItem: () => saved || null,
      setItem: (_: string, value: string) => { saved = value; } });
    saveLayout({ ...defaultLayout, sidebarOpen: false, panelHeight: 310 });
    expect(readLayout()).toEqual({ ...defaultLayout, sidebarOpen: false, panelHeight: 310 });
  });
  it("ignores corrupt storage", () => {
    vi.stubGlobal("localStorage", { getItem: () => "not JSON" });
    expect(readLayout()).toEqual(defaultLayout);
  });
});
