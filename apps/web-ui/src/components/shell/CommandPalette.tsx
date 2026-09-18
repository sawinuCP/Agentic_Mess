// Command palette (Wave 6 Phase 4): searchable, keyboard-first command surface.
//
// Commands come from the pure registry (`commands/registry.ts`); the palette
// owns only presentation and interaction. Focus is moved into the input on
// open, Escape closes, arrow navigation skips disabled commands, and the
// palette always restores focus to the workspace when it closes — see
// docs/frontend-interaction-model.md for the interaction contract.

import { useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "../../state/store";
import { cancelTask, controlTask } from "../../api/client";
import { errorMessage } from "../../api/errors";
import { taskCommands } from "../../commands/taskCommands";
import { runningAgents, useOffice } from "../../state/officeStore";
import {
  buildCommands,
  filterCommands,
  firstSelectable,
  nextSelectable,
  type Command,
} from "../../commands/registry";

export default function CommandPalette() {
  const project = useStore((s) => s.project);
  const toolchains = useStore((s) => s.toolchains);
  const tabs = useStore((s) => s.tabs);
  const activePath = useStore((s) => s.activePath);
  const selection = useStore((s) => s.selection);
  const output = useStore((s) => s.output);
  const setFn = useStore((s) => s.set);
  const runTool = useStore((s) => s.runTool);
  const openTerminal = useStore((s) => s.createTerminal);
  const setOffice = useOffice((s) => s.set);
  const agents = useOffice((s) => s.agents);
  const tasks = useOffice((s) => s.tasks);
  const officeProjectId = useOffice((s) => s.projectId);
  const running = runningAgents(agents).length;

  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const executing = useRef(false);
  const [selected, setSelected] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const restoreFocusRef = useRef<Element | null>(null);

  useEffect(() => {
    restoreFocusRef.current = document.activeElement;
    inputRef.current?.focus();
    return () => {
      const restore = restoreFocusRef.current;
      if (restore instanceof HTMLElement) restore.focus();
    };
  }, []);

  const commands = useMemo(
    () =>
      buildCommands(
        {
          hasProject: project !== null,
          hasTestRunner:
            toolchains?.languages.some((l) => l.tools.includes("test")) ?? false,
          hasLinter: toolchains?.languages.some((l) => l.tools.includes("lint")) ?? false,
          hasFormatter:
            toolchains?.languages.some((l) => l.tools.includes("format")) ?? false,
          hasRunner: toolchains?.languages.some((l) => l.tools.includes("run")) ?? false,
          hasBuilder: toolchains?.languages.some((l) => l.tools.includes("build")) ?? false,
          activeFilePath:
            tabs.find((t) => t.kind === "file" && t.path === activePath && !t.isBinary)
              ?.path ?? null,
          hasSelection: selection !== null,
          hasFailure:
            (output?.exit_code !== null && output?.exit_code !== undefined && output.exit_code !== 0) ||
            tasks.some((t) => t.status === "failed"),
        },
        {
          setView: (view) => setFn({ view, sidebarOpen: true }),
          setOfficeTab: (tab) => setOffice({ tab }),
          openQuickOpen: () => setFn({ quickOpen: true }),
          openSymbolSearch: () => setFn({ symbolSearch: true }),
          openCommandCenter: (prefill) => {
            if (prefill) setFn({ centerPrefill: prefill });
            setFn({ view: "command", sidebarOpen: true });
          },
          openSpawnDialog: () => {
            setFn({ view: "office", sidebarOpen: true });
            setOffice({ tab: "team", spawnDialog: true });
          },
          openTaskDialog: () => {
            setFn({ view: "office", sidebarOpen: true });
            setOffice({ tab: "team", taskDialog: true });
          },
          openMcpDialog: () => setFn({ mcpDialog: true }),
          openProjectDialog: () => setFn({ projectDialog: true }),
          openTerminal: () => openTerminal(),
          showToolOutput: () => setFn({ panelOpen: true, panelTab: "output" }),
          openSystemDiagnostics: () => setFn({ diagnosticsOpen: true }),
          runTool: (tool, path) => runTool(tool, path),
        },
      ),
    [project, toolchains, tabs, activePath, selection, output, tasks, setFn, setOffice, runTool, openTerminal],
  );

  const executionCommands = useMemo(() => taskCommands(
    project?.id === officeProjectId ? tasks : [],
    async (id, action) => {
      const task = useOffice.getState().tasks.find((t) => t.id === id);
      if (!task || task.project_id !== useStore.getState().project?.id) throw new Error("Task is no longer in this project.");
      const current = taskCommands(useOffice.getState().tasks, async () => undefined)
        .find((command) => command.id === `task.${id}.${action}`);
      if (current?.disabledReason) throw new Error(current.disabledReason);
      const message = action === "execute"
        ? `Start execution of ${task.title}? This may run tools and use configured model providers.`
        : action === "cancel"
          ? `Cancel ${task.title}? Its history is preserved and the status becomes cancelled.`
          : action === "retry"
            ? `Re-run ${task.title}? A new execution run starts; recorded attempts are preserved.`
            : `Send ${action} to ${task.title}? Acknowledgement does not mean the workflow has reached a checkpoint.`;
      if (!window.confirm(message)) return;
      if (action === "cancel") {
        await cancelTask(id);
        useStore.getState().set({ notice: `Task cancelled: ${task.title}. Follow its recorded state in Office.` });
        return;
      }
      if (action === "retry") {
        await controlTask(id, "execute");
        useStore.getState().set({ notice: `Retry dispatched for ${task.title}. A new execution run starts.` });
        return;
      }
      await controlTask(id, action);
      useStore.getState().set({ notice: action === "execute"
        ? `Execution dispatch acknowledged for ${task.title}. Follow its recorded state in Office.`
        : `${action} signal acknowledged for ${task.title}. Awaiting workflow checkpoint; recorded status is unchanged.` });
    }), [project?.id, officeProjectId, tasks]);
  const filtered = useMemo(() => filterCommands([...commands, ...executionCommands], query), [commands, executionCommands, query]);

  // Keep selection on a selectable row when the filter result changes.
  useEffect(() => {
    setSelected(firstSelectable(filtered));
  }, [filtered]);

  useEffect(() => {
    const row = listRef.current?.querySelector("li.selected");
    row?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  const execute = async (command: Command | undefined) => {
    if (!command || command.disabledReason || executing.current) return;
    executing.current = true;
    setBusy(true);
    setError(null);
    try {
      await command.run();
      setFn({ commandPalette: false });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      executing.current = false;
      setBusy(false);
    }
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    // The combobox is the modal's only tab stop; rows use arrow navigation.
    if (event.key === "Tab") {
      event.preventDefault();
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      setFn({ commandPalette: false });
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setSelected((current) => nextSelectable(filtered, current, 1));
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setSelected((current) => nextSelectable(filtered, current, -1));
    }
    if (event.key === "Enter") {
      event.preventDefault();
      // Recompute from the live input value: the highlighted index can lag a
      // fast keystroke behind the rendered list, which would run the wrong
      // command (or nothing). The DOM value is always current.
      const live = (event.target as HTMLInputElement).value;
      const fresh = filterCommands([...commands, ...executionCommands], live);
      execute(fresh[firstSelectable(fresh)] ?? undefined);
    }
  };

  return (
    <div
      className="overlay command-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
      onClick={() => setFn({ commandPalette: false })}
    >
      <div className="dialog command-palette" onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          className="text-input"
          role="combobox"
          aria-expanded="true"
          aria-controls="command-palette-list"
          aria-activedescendant={
            selected >= 0 && filtered[selected] ? `command-palette-${filtered[selected].id}` : undefined
          }
          aria-label="Search commands"
          placeholder="Type a command…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <ul
          id="command-palette-list"
          ref={listRef}
          className="command-list"
          role="listbox"
          aria-label="Commands"
        >
          {filtered.map((command, index) => (
            <li
              key={command.id}
              id={`command-palette-${command.id}`}
              className={`command-row ${index === selected ? "selected" : ""} ${
                command.disabledReason ? "disabled" : ""
              }`}
              role="option"
              aria-selected={index === selected}
              aria-disabled={command.disabledReason ? true : undefined}
              title={command.disabledReason}
              onClick={() => execute(command)}
              onMouseEnter={() => !command.disabledReason && setSelected(index)}
            >
              <span className="command-label">{command.label}</span>
              <span className="command-meta">
                {command.shortcut && <kbd className="command-kbd">{command.shortcut}</kbd>}
                <span className="command-category">{command.category}</span>
                {command.disabledReason && (
                  <span className="command-reason">{command.disabledReason}</span>
                )}
              </span>
            </li>
          ))}
          {filtered.length === 0 && (
            <li className="command-empty muted small" aria-live="polite">
              No matching commands
            </li>
          )}
        </ul>
        {busy && <p role="status">Running command…</p>}
        {error && <p className="error-text" role="alert">{error}</p>}
        <div className="command-hint muted small">
          <span>↑↓ navigate</span>
          <span>↵ run</span>
          <span>esc close</span>
          {running > 0 && (
            <span>
              {running} agent{running === 1 ? "" : "s"} running
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
