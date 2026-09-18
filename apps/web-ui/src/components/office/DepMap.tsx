// Dependency map (Wave 7 completion): a lightweight, read-only task DAG —
// NOT the full Execution Graph (a separate future wave). Nodes are layered
// by dependency depth with status treatment + text labels; every node is a
// keyboard-focusable button jumping to the task inspector, and the same
// edges exist as a textual list right below for screen readers.

import { useMemo } from "react";
import { glue } from "@typehug/en";

import {
  DEP_NODE_H,
  DEP_NODE_W,
  layoutDeps,
} from "../../office/selectors";
import type { TaskInfo } from "../../types";
import { useOffice } from "../../state/officeStore";

const NODE_FILL: Record<string, string> = {
  completed: "var(--ok-bg)",
  failed: "var(--down-bg)",
  cancelled: "var(--muted-bg)",
  running: "var(--surface-elevated)",
  blocked: "var(--warn-bg)",
  ready: "var(--surface-elevated)",
};

function short(title: string): string {
  return title.length > 18 ? `${title.slice(0, 17)}…` : title;
}

export default function DepMap({ tasks }: { tasks: TaskInfo[] }) {
  const setOffice = useOffice((s) => s.set);
  const { nodes, edges, width, height } = useMemo(() => layoutDeps(tasks), [tasks]);
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);

  if (tasks.length === 0) return null;

  return (
    <div className="dep-map">
      <div className="dep-scroll">
        <svg
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          role="group"
          aria-label={`Dependency map of ${tasks.length} tasks`}
        >
          <defs>
            <marker id="dep-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
              <path d="M0,0 L8,4 L0,8" fill="none" stroke="var(--muted)" strokeWidth="1.2" />
            </marker>
          </defs>
          {edges.map((edge) => {
            const from = byId.get(edge.from);
            const to = byId.get(edge.to);
            if (!from || !to) return null;
            const x1 = from.x + DEP_NODE_W / 2;
            const y1 = from.y + DEP_NODE_H;
            const x2 = to.x + DEP_NODE_W / 2;
            const y2 = to.y;
            return (
              <line
                key={`${edge.from}->${edge.to}`}
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2 - 2}
                stroke="var(--muted)"
                strokeWidth="1.2"
                markerEnd="url(#dep-arrow)"
              />
            );
          })}
          {nodes.map((node) => (
            <g
              key={node.id}
              role="button"
              tabIndex={0}
              aria-label={`Inspect task ${node.title}, ${node.status.replaceAll("_", " ")}`}
              className="dep-node"
              onClick={() => setOffice({ selectedTaskId: node.id })}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setOffice({ selectedTaskId: node.id });
                }
              }}
            >
              <title>{`${node.title} (${node.status.replaceAll("_", " ")})`}</title>
              <rect
                x={node.x}
                y={node.y}
                width={DEP_NODE_W}
                height={DEP_NODE_H}
                rx={6}
                fill={NODE_FILL[node.status] ?? "var(--surface-panel)"}
                stroke="var(--border-strong)"
              />
              <text x={node.x + 8} y={node.y + 15} className="dep-title">
                {short(node.title)}
              </text>
              <text x={node.x + 8} y={node.y + 28} className="dep-status">
                {node.status.replaceAll("_", " ")}
              </text>
            </g>
          ))}
        </svg>
      </div>
      <ul className="dep-list small">
        {tasks
          .filter((t) => t.depends_on.length > 0)
          .map((t) => (
            <li key={t.id}>
              {t.title} waits for{" "}
              {t.depends_on.map((dep, i) => {
                const target = tasks.find((o) => o.id === dep);
                return (
                  <span key={dep}>
                    {i > 0 && ", "}
                    {target ? (
                      <button className="link mono" onClick={() => setOffice({ selectedTaskId: target.id })}>
                        {target.title}
                      </button>
                    ) : (
                      <span className="mono muted">{glue("external task")}</span>
                    )}
                  </span>
                );
              })}
            </li>
          ))}
      </ul>
    </div>
  );
}
