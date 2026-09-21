// Execution Graph view (Wave 8): operational requirement→evidence lineage.
//
// Main-area view built as a memoized pure projection over the office
// snapshot (agents/tasks/events/traceability/worktrees). No new backend,
// no graph library, no polling. Selection syncs both ways with the Agent
// Office through shared store fields; graph-only UI state (pan/zoom,
// filters, mode) stays local.

import { useEffect, useMemo, useRef, useState } from "react";

import { listRequirements } from "../../api/client";
import {
  AUTHORITY_LABEL,
  EDGE_EXPLANATION,
  GRAPH_GAP_X,
  GRAPH_NODE_H,
  GRAPH_NODE_W,
  buildGraph,
  coverageCounts,
  emptyFilter,
  filterGraph,
  graphDimensions,
  layoutGraph,
  textTree,
  type GraphAuthority,
  type GraphEdge,
  type GraphFilter,
  type GraphNode,
  type GraphNodeType,
  type TextNode,
} from "../../graph/build";
import { useOffice } from "../../state/officeStore";
import { useStore } from "../../state/store";
import type { RequirementInfo } from "../../types";
import { UiState } from "../shell/UiState";
import GraphDetail from "./GraphDetail";

const ALL_TYPES: GraphNodeType[] = [
  "requirement",
  "task",
  "agent",
  "file",
  "commit",
  "test",
  "evidence",
];

const TYPE_LABEL: Record<GraphNodeType, string> = {
  requirement: "Requirements",
  task: "Tasks",
  agent: "Agents",
  file: "Files",
  commit: "Commits",
  test: "Tests",
  evidence: "Evidence",
};

const ALL_AUTHORITIES: GraphAuthority[] = ["persisted", "event-derived", "inferred"];

const AUTHORITY_HINT: Record<GraphAuthority, string> = {
  persisted: "database row",
  "event-derived": "recorded events",
  inferred: "heuristic",
};

/** Line treatment per authority: never color alone (§24). */
function edgeStroke(e: GraphEdge): { stroke: string; width: number; dash: string | undefined } {
  if (e.authority === "inferred") return { stroke: "var(--warn)", width: 1.6, dash: "2 3" };
  if (e.authority === "event-derived") return { stroke: "var(--muted)", width: 1.1, dash: "7 3" };
  return { stroke: "var(--muted)", width: 1.1, dash: undefined };
}

function edgeTitle(e: GraphEdge): string {
  const entry = EDGE_EXPLANATION[e.type];
  const label = AUTHORITY_LABEL[e.authority];
  return entry ? `${e.type} — ${label}: ${entry.reason}` : `${e.type} — ${label}`;
}

function nodeById(nodes: GraphNode[], id: string | null): GraphNode | null {
  if (!id) return null;
  return nodes.find((n) => n.id === id) ?? null;
}

export default function GraphView() {
  const project = useStore((s) => s.project);
  const agents = useOffice((s) => s.agents);
  const tasks = useOffice((s) => s.tasks);
  const events = useOffice((s) => s.events);
  const traceability = useOffice((s) => s.traceability);
  const worktrees = useOffice((s) => s.worktrees);
  const storeTaskId = useOffice((s) => s.selectedTaskId);
  const storeAgentId = useOffice((s) => s.selectedAgentId);
  const storeReqId = useOffice((s) => s.selectedRequirementId);
  const setOffice = useOffice((s) => s.set);
  const loadWorktrees = useOffice((s) => s.loadWorktrees);

  const [rawRequirements, setRawRequirements] = useState<RequirementInfo[]>([]);
  const [reqError, setReqError] = useState<string | null>(null);
  const [mode, setMode] = useState<"graph" | "text">("graph");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [types, setTypes] = useState<Set<GraphNodeType>>(new Set(ALL_TYPES));
  const [authorities, setAuthorities] = useState<Set<GraphAuthority>>(new Set(ALL_AUTHORITIES));
  const [failuresOnly, setFailuresOnly] = useState(false);
  const [focusReq, setFocusReq] = useState("all");
  const [focusTask, setFocusTask] = useState("all");
  const [focusAgent, setFocusAgent] = useState("all");
  const [query, setQuery] = useState("");
  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 });
  const containerRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ startX: number; startY: number; moved: boolean } | null>(null);

  useEffect(() => {
    if (!project) return;
    let active = true;
    listRequirements(project.id)
      .then((rows) => { if (active) { setRawRequirements(rows); setReqError(null); } })
      .catch((err: unknown) => { if (active) setReqError(err instanceof Error ? err.message : String(err)); });
    // Worktrees resolve task→commit edges; the store guards duplicate loads.
    void loadWorktrees().catch(() => undefined);
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project]);

  const graph = useMemo(
    () =>
      buildGraph({
        report: traceability
          ? {
              requirements: traceability.requirements,
              coverage: traceability.coverage,
              generatedAt: traceability.generated_at,
            }
          : null,
        rawRequirements,
        tasks,
        agents,
        events,
        worktrees,
      }),
    [traceability, rawRequirements, tasks, agents, events, worktrees],
  );

  const filter: GraphFilter = useMemo(
    () => ({
      ...emptyFilter(),
      types: types.size === ALL_TYPES.length ? null : types,
      authorities: authorities.size === ALL_AUTHORITIES.length ? null : authorities,
      focusRequirementId: focusReq === "all" ? null : focusReq,
      focusTaskId: focusTask === "all" ? null : focusTask,
      focusAgentId: focusAgent === "all" ? null : focusAgent,
      failuresOnly,
      query,
    }),
    [types, authorities, focusReq, focusTask, focusAgent, failuresOnly, query],
  );
  const visible = useMemo(() => filterGraph(graph, filter), [graph, filter]);
  const positions = useMemo(() => layoutGraph(visible.nodes), [visible.nodes]);
  const dims = useMemo(() => graphDimensions(positions), [positions]);
  const coverage = useMemo(
    () => coverageCounts(traceability?.requirements ?? [], tasks),
    [traceability, tasks],
  );
  const unlinked = useMemo(
    () => tasks.filter((t) => !graph.edges.some((e) => e.target === `task:${t.id}` && e.type === "planned for")),
    [tasks, graph],
  );

  // Follow office selection while the graph is open (both directions sync).
  useEffect(() => {
    if (storeTaskId) setSelectedId(`task:${storeTaskId}`);
    else if (storeAgentId) setSelectedId(`agent:${storeAgentId}`);
    else if (storeReqId) setSelectedId(`req:${storeReqId}`);
  }, [storeTaskId, storeAgentId, storeReqId]);

  const selected = nodeById(visible.nodes, selectedId) ?? nodeById(graph.nodes, selectedId);

  const select = (node: GraphNode | null): void => {
    setSelectedId(node?.id ?? null);
    if (!node) return;
    if (node.type === "task") {
      setOffice({ selectedTaskId: node.taskId, selectedAgentId: null, selectedRequirementId: node.requirementId });
    } else if (node.type === "agent") {
      setOffice({ selectedAgentId: node.agentId, selectedTaskId: null, selectedRequirementId: null });
    } else if (node.type === "requirement") {
      setOffice({ selectedRequirementId: node.requirementId, selectedTaskId: null, selectedAgentId: null });
    }
  };

  const toggleType = (type: GraphNodeType): void => {
    setTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  };

  const toggleAuthority = (authority: GraphAuthority): void => {
    setAuthorities((prev) => {
      const next = new Set(prev);
      if (next.has(authority)) next.delete(authority);
      else next.add(authority);
      return next;
    });
  };
  const authorityActive = (a: GraphAuthority): boolean => authorities.has(a);

  const fit = (): void => {
    const el = containerRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const k = Math.max(0.2, Math.min(1.5, Math.min(rect.width / Math.max(1, dims.width), rect.height / Math.max(1, dims.height))));
    setTransform({ k, x: (rect.width - dims.width * k) / 2, y: 16 });
  };

  useEffect(() => {
    fit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dims.width, dims.height]);

  const centerOn = (id: string): void => {
    const el = containerRef.current;
    const pos = positions.get(id);
    if (!el || !pos) return;
    const rect = el.getBoundingClientRect();
    setTransform((t) => ({
      ...t,
      x: rect.width / 2 - (pos.x * (GRAPH_NODE_W + GRAPH_GAP_X) + GRAPH_NODE_W / 2) * t.k,
      y: rect.height / 2 - (pos.y + GRAPH_NODE_H / 2) * t.k,
    }));
  };

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent): void => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      setTransform((t) => {
        const k = Math.max(0.25, Math.min(2.5, t.k * Math.exp(-e.deltaY * 0.0012)));
        const s = k / t.k;
        return { k, x: px - (px - t.x) * s, y: py - (py - t.y) * s };
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const onCanvasKey = (e: React.KeyboardEvent): void => {
    if (e.key === "+" || e.key === "=") setTransform((t) => ({ ...t, k: Math.min(2.5, t.k * 1.2) }));
    else if (e.key === "-") setTransform((t) => ({ ...t, k: Math.max(0.25, t.k / 1.2) }));
    else if (e.key === "0") fit();
    else if (e.key.startsWith("Arrow")) {
      e.preventDefault();
      const step = 40;
      setTransform((t) => ({
        ...t,
        x: t.x + (e.key === "ArrowLeft" ? step : e.key === "ArrowRight" ? -step : 0),
        y: t.y + (e.key === "ArrowUp" ? step : e.key === "ArrowDown" ? -step : 0),
      }));
    }
  };

  const posOf = (id: string): { x: number; y: number } | undefined => positions.get(id);
  const edgePath = (e: GraphEdge): string | null => {
    const from = posOf(e.source);
    const to = posOf(e.target);
    if (!from || !to) return null;
    const x1 = from.x * (GRAPH_NODE_W + GRAPH_GAP_X) + GRAPH_NODE_W;
    const y1 = from.y + GRAPH_NODE_H / 2;
    const x2 = to.x * (GRAPH_NODE_W + GRAPH_GAP_X);
    const y2 = to.y + GRAPH_NODE_H / 2;
    const mid = (x1 + x2) / 2;
    return `M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`;
  };
  const neighborIds = useMemo(() => {
    if (!selectedId) return null;
    const out = new Set<string>([selectedId]);
    for (const e of visible.edges) {
      if (e.source === selectedId) out.add(e.target);
      if (e.target === selectedId) out.add(e.source);
    }
    return out;
  }, [selectedId, visible.edges]);

  if (!project) {
    return <div className="graph-empty muted">Open a project to see the execution graph.</div>;
  }
  if (!traceability) {
    return (
      <div className="graph-empty">
        <UiState title="Waiting for oversight data…">
          The graph builds from the traceability snapshot once the office stream connects.
        </UiState>
      </div>
    );
  }

  const typeActive = (t: GraphNodeType): boolean => types.has(t);

  return (
    <div className="graph-view">
      <div className="graph-header">
        <span className="strong">Execution graph</span>
        <span className="small muted" title={`traceability generated ${new Date(traceability.generated_at).toLocaleString()}`}>
          {coverage.requirements.total} requirements · {coverage.requirements.verified} verified ·{" "}
          {coverage.requirements.failed} failed · {coverage.requirements.unknown} unknown
        </span>
        <span className="small muted">
          {coverage.criteria.verified}/{coverage.criteria.total} criteria verified
        </span>
        {unlinked.length > 0 && (
          <span className="small warn" title={unlinked.map((t) => t.title).join(", ")}>
            {unlinked.length} unlinked task{unlinked.length === 1 ? "" : "s"}
          </span>
        )}
        <div className="status-spacer" />
        <button
          className={`btn btn-small ${mode === "graph" ? "" : "secondary"}`}
          aria-pressed={mode === "graph"}
          onClick={() => setMode(mode === "graph" ? "text" : "graph")}
        >
          {mode === "graph" ? "Text view" : "Graph view"}
        </button>
      </div>
      {reqError && (
        <div className="error-text small" role="alert">
          Requirement descriptions unavailable: {reqError}
        </div>
      )}
      <div className="graph-toolbar" role="toolbar" aria-label="Graph controls">
        <div className="row wrap" role="group" aria-label="Node type filter">
          {ALL_TYPES.map((t) => (
            <button
              key={t}
              className={`chip ${typeActive(t) ? "active" : ""}`}
              aria-pressed={typeActive(t)}
              onClick={() => toggleType(t)}
            >
              {TYPE_LABEL[t].toLowerCase()}
            </button>
          ))}
          <button
            className={`chip ${failuresOnly ? "active" : ""}`}
            aria-pressed={failuresOnly}
            onClick={() => setFailuresOnly((v) => !v)}
          >
            failures
          </button>
        </div>
        <div className="row wrap" role="group" aria-label="Relationship authority filter">
          {ALL_AUTHORITIES.map((a) => (
            <button
              key={a}
              className={`chip ${authorityActive(a) ? "active" : ""}`}
              aria-pressed={authorityActive(a)}
              title={`${AUTHORITY_LABEL[a]}: ${AUTHORITY_HINT[a]}`}
              onClick={() => toggleAuthority(a)}
            >
              {AUTHORITY_LABEL[a].toLowerCase()}
            </button>
          ))}
        </div>
        <div className="graph-legend" role="note" aria-label="Relationship authority legend">
          <span className="strong small">Edges:</span>
          <span className="small" title="PERSISTED: database row">
            <svg width="26" height="8" aria-hidden="true"><line x1="0" y1="4" x2="26" y2="4" stroke="currentColor" strokeWidth="1.5" /></svg>{" "}
            persisted
          </span>
          <span className="small" title="EVENT-DERIVED: recorded events">
            <svg width="26" height="8" aria-hidden="true"><line x1="0" y1="4" x2="26" y2="4" stroke="currentColor" strokeWidth="1.5" strokeDasharray="7 3" /></svg>{" "}
            event-derived
          </span>
          <span className="small" title="INFERRED: heuristic, never authoritative">
            <svg width="26" height="8" aria-hidden="true"><line x1="0" y1="4" x2="26" y2="4" stroke="var(--warn)" strokeWidth="1.5" strokeDasharray="2 3" /></svg>{" "}
            inferred
          </span>
        </div>
        <div className="row wrap gap4">
          <label className="small muted row gap4">
            Requirement
            <select className="text-input small" aria-label="Focus requirement" value={focusReq} onChange={(e) => setFocusReq(e.target.value)}>
              <option value="all">all</option>
              {traceability.requirements.map((r) => (
                <option key={r.id} value={r.id}>{r.title}</option>
              ))}
            </select>
          </label>
          <label className="small muted row gap4">
            Task
            <select className="text-input small" aria-label="Focus task" value={focusTask} onChange={(e) => setFocusTask(e.target.value)}>
              <option value="all">all</option>
              {tasks.map((t) => (
                <option key={t.id} value={t.id}>{t.title}</option>
              ))}
            </select>
          </label>
          <label className="small muted row gap4">
            Agent
            <select className="text-input small" aria-label="Focus agent" value={focusAgent} onChange={(e) => setFocusAgent(e.target.value)}>
              <option value="all">all</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </label>
          <input
            className="text-input small"
            aria-label="Search graph"
            placeholder="Search nodes…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        {mode === "graph" && (
          <div className="row gap4">
            <button className="btn btn-small" aria-label="Zoom in" onClick={() => setTransform((t) => ({ ...t, k: Math.min(2.5, t.k * 1.2) }))}>+</button>
            <button className="btn btn-small" aria-label="Zoom out" onClick={() => setTransform((t) => ({ ...t, k: Math.max(0.25, t.k / 1.2) }))}>−</button>
            <button className="btn btn-small" onClick={fit}>Fit</button>
            <button className="btn btn-small" disabled={!selectedId} onClick={() => selectedId && centerOn(selectedId)}>
              Center selection
            </button>
          </div>
        )}
      </div>
      {(visible.hidden > 0 || graph.hiddenFiles > 0 || graph.hiddenEvidence > 0) && (
        <div className="small muted pad-h" role="note">
          {visible.hidden > 0 && `${visible.hidden} hidden by filters. `}
          {graph.hiddenFiles > 0 && `${graph.hiddenFiles} more files. `}
          {graph.hiddenEvidence > 0 && `${graph.hiddenEvidence} more evidence items. `}
          Filtering never invents relationships.
        </div>
      )}
      <div className="graph-body">
        {mode === "graph" ? (
          <div
            ref={containerRef}
            className="graph-canvas"
            tabIndex={0}
            role="group"
            aria-label="Execution graph canvas. Arrow keys pan, plus and minus zoom, zero fits."
            onKeyDown={onCanvasKey}
            onPointerDown={(e) => {
              if (e.button !== 0) return;
              // Node presses belong to the node (click/keyboard select);
              // only empty-canvas presses start a pan (with capture).
              if ((e.target as HTMLElement).closest(".graph-node")) return;
              (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
              dragRef.current = { startX: e.clientX - transform.x, startY: e.clientY - transform.y, moved: false };
            }}
            onPointerMove={(e) => {
              const drag = dragRef.current;
              if (!drag) return;
              const nx = e.clientX - drag.startX;
              const ny = e.clientY - drag.startY;
              if (Math.abs(nx - transform.x) + Math.abs(ny - transform.y) > 4) drag.moved = true;
              setTransform((t) => ({ ...t, x: nx, y: ny }));
            }}
            onPointerUp={() => { dragRef.current = null; }}
          >
            <svg
              style={{ width: "100%", height: "100%", display: "block" }}
              role="img"
              aria-label={`${visible.nodes.length} nodes, ${visible.edges.length} relationships`}
            >
              <g transform={`translate(${transform.x},${transform.y}) scale(${transform.k})`}>
                {visible.edges.map((e) => {
                  const d = edgePath(e);
                  if (!d) return null;
                  const stroke = edgeStroke(e);
                  return (
                    <path
                      key={e.id}
                      d={d}
                      fill="none"
                      stroke={stroke.stroke}
                      strokeWidth={stroke.width}
                      strokeDasharray={stroke.dash}
                      opacity={0.75}
                    >
                      <title>{edgeTitle(e)}</title>
                    </path>
                  );
                })}
                {visible.nodes.map((n) => {
                  const pos = positions.get(n.id);
                  if (!pos) return null;
                  const x = pos.x * (GRAPH_NODE_W + GRAPH_GAP_X);
                  const dimmed = neighborIds && !neighborIds.has(n.id);
                  const activate = (): void => {
                    if (dragRef.current?.moved) return;
                    select(n);
                  };
                  return (
                    <g key={n.id} opacity={dimmed ? 0.35 : 1}>
                      <title>{`${n.type}: ${n.label} — ${n.status.replaceAll("_", " ")}`}</title>
                      <rect
                        x={x}
                        y={pos.y}
                        width={GRAPH_NODE_W}
                        height={GRAPH_NODE_H}
                        rx={6}
                        className={`graph-rect graph-node tone-${n.tone} ${selectedId === n.id ? "selected" : ""}`}
                        role="button"
                        tabIndex={0}
                        aria-label={`${n.type}: ${n.label}, ${n.status.replaceAll("_", " ")}`}
                        onClick={activate}
                        onKeyDown={(ev) => {
                          if (ev.key === "Enter" || ev.key === " ") {
                            ev.preventDefault();
                            select(n);
                          }
                        }}
                      />
                      <text x={x + 8} y={pos.y + 17} className="graph-label" pointerEvents="none">
                        {n.label.length > 22 ? `${n.label.slice(0, 21)}…` : n.label}
                      </text>
                      <text x={x + 8} y={pos.y + 32} className="graph-status" pointerEvents="none">
                        {n.type} · {n.status.replaceAll("_", " ")}
                      </text>
                    </g>
                  );
                })}
              </g>
            </svg>
          </div>
        ) : (
          <div className="graph-text">
            <ul>
              {traceability.requirements.map((r) => {
                const tree = textTree(r.id, graph, tasks);
                if (!tree) return null;
                return <TextTreeView key={r.id} node={tree} graph={graph} onSelect={select} />;
              })}
            </ul>
            {unlinked.length > 0 && (
              <div className="stack">
                <strong className="small">Unlinked tasks (no requirement edge)</strong>
                {unlinked.map((t) => (
                  <button key={t.id} className="link small" onClick={() => select(nodeById(graph.nodes, `task:${t.id}`))}>
                    Task: {t.title} ({t.status.replaceAll("_", " ")})
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        <GraphDetail
          node={selected}
          graph={graph}
          tasks={tasks}
          agents={agents}
          events={events}
          rawRequirements={rawRequirements}
          traceability={traceability}
          onSelect={select}
          onCenter={centerOn}
        />
      </div>
    </div>
  );
}

function TextTreeView({ node, graph, onSelect }: {
  node: TextNode;
  graph: { nodes: GraphNode[] };
  onSelect: (node: GraphNode | null) => void;
}) {
  const target = node.nodeId ? graph.nodes.find((n) => n.id === node.nodeId) ?? null : null;
  return (
    <li>
      {target ? (
        <button className="link" onClick={() => onSelect(target)}>
          {node.label}
        </button>
      ) : (
        <span>{node.label}</span>
      )}
      {node.detail && <span className="muted small"> — {node.detail}</span>}
      {node.children.length > 0 && (
        <ul>
          {node.children.map((child, i) => (
            <TextTreeView key={`${child.label}-${i}`} node={child} graph={graph} onSelect={onSelect} />
          ))}
        </ul>
      )}
    </li>
  );
}
