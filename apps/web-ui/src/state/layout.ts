// Layout preferences only: never persist project buffers, credentials or execution data.
export const defaultLayout = { sidebarOpen: true, sidebarWidth: 280, panelOpen: true, panelHeight: 240 };
export function clampSize(value: number, min: number, max: number): number {
  return Number.isFinite(value) ? Math.max(min, Math.min(max, value)) : min;
}
export function readLayout(): typeof defaultLayout {
  try {
    const value = JSON.parse(localStorage.getItem("harness.layout.v1") ?? "{}");
    return {
      sidebarOpen: typeof value.sidebarOpen === "boolean" ? value.sidebarOpen : true,
      panelOpen: typeof value.panelOpen === "boolean" ? value.panelOpen : true,
      sidebarWidth: clampSize(Number(value.sidebarWidth ?? 280), 160, 600),
      panelHeight: clampSize(Number(value.panelHeight ?? 240), 100, 700),
    };
  } catch { return { ...defaultLayout }; }
}
export function saveLayout(value: typeof defaultLayout): void {
  try { localStorage.setItem("harness.layout.v1", JSON.stringify(value)); } catch { /* storage may be disabled */ }
}
