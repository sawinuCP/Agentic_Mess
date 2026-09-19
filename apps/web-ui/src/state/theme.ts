// Color theme contract (Wave 6): dark default, light opt-in.
//
// Persisted in localStorage; applied as `data-theme` on <html> so the CSS
// variable layer and Monaco/xterm themes follow one source of truth. Pure
// helpers are unit-testable in node (DOM/storage access is guarded).

export type ThemeId = "dark" | "light";

const STORAGE_KEY = "harness.theme.v1";

export function readTheme(): ThemeId {
  try {
    return localStorage.getItem(STORAGE_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark"; // storage unavailable — dark is the built-in default
  }
}

export function saveTheme(theme: ThemeId): void {
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Storage may be disabled; the session value still applies.
  }
}

export function applyTheme(theme: ThemeId): void {
  saveTheme(theme);
  if (typeof document !== "undefined") {
    document.documentElement.dataset.theme = theme;
  }
}

export interface XtermTheme {
  background: string;
  foreground: string;
  cursor: string;
  selectionBackground: string;
}

/** xterm.js theme matching the app theme (terminals follow the toggle live). */
export function xtermTheme(theme: ThemeId): XtermTheme {
  return theme === "light"
    ? {
        background: "#f4f5f7",
        foreground: "#2a2f3a",
        cursor: "#2f5fd0",
        selectionBackground: "#c3d0ea",
      }
    : {
        background: "#0d1017",
        foreground: "#d6dbe6",
        cursor: "#5b8cff",
        selectionBackground: "#2a3650",
      };
}
