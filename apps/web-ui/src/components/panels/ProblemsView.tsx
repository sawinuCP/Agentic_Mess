import { useOffice } from "../../state/officeStore";
import { useStore } from "../../state/store";
import { collectProblems } from "../../office/selectors";
import { StatusLabel, UiState } from "../shell/UiState";

// Problems view: triage surface over already-loaded store state (Wave 6).
//
// No new fetches — failed/blocked tasks, the last tool result and pending
// approvals are all in the workspace and office stores. Every row navigates
// somewhere real (office inspector, output panel, oversight tab); destructive
// actions stay behind the existing confirmations in the Team tab.

const KIND_LABEL: Record<string, string> = {
  "task-failed": "Task failed",
  "task-blocked": "Task blocked",
  "tool-failed": "Tool failed",
  "approval-pending": "Approval needed",
};

export default function ProblemsView() {
  const project = useStore((s) => s.project);
  const output = useStore((s) => s.output);
  const setFn = useStore((s) => s.set);
  const tasks = useOffice((s) => s.tasks);
  const hitl = useOffice((s) => s.hitl);
  const setOffice = useOffice((s) => s.set);

  if (!project) {
    return <aside className="sidebar"><p className="muted pad">Open a project first.</p></aside>;
  }

  const problems = collectProblems({ tasks, output, hitl });

  const inspectTask = (taskId: string | null) => {
    if (taskId) setOffice({ selectedTaskId: taskId });
    setFn({ view: "office", sidebarOpen: true });
    setOffice({ tab: "team" });
  };

  return (
    <aside className="sidebar">
      <header className="sidebar-header">PROBLEMS</header>
      <div className="pad stack">
        {problems.length === 0 ? (
          <UiState title="No problems recorded">
            <span>Failed tasks, blocked work, tool failures and pending approvals will appear here.</span>
          </UiState>
        ) : (
          <ul className="plain-list stack">
            {problems.map((problem, index) => (
              <li key={`${problem.kind}-${problem.taskId ?? "tool"}-${index}`} className="card">
                <div className="row between">
                  <StatusLabel
                    state={
                      problem.kind === "approval-pending"
                        ? "requires_approval"
                        : problem.kind === "task-blocked"
                          ? "blocked"
                          : "failed"
                    }
                  />
                  <span className="muted small">{KIND_LABEL[problem.kind]}</span>
                </div>
                <p className="strong">{problem.title}</p>
                <p className="muted small">{problem.detail}</p>
                <div className="row">
                  {problem.taskId && (
                    <button className="button secondary" onClick={() => inspectTask(problem.taskId)}>
                      Inspect task
                    </button>
                  )}
                  {problem.kind === "tool-failed" && (
                    <button
                      className="button secondary"
                      onClick={() => setFn({ panelOpen: true, panelTab: "output" })}
                    >
                      Show output
                    </button>
                  )}
                  {problem.kind === "approval-pending" && (
                    <button
                      className="button secondary"
                      onClick={() => {
                        setFn({ view: "office", sidebarOpen: true });
                        setOffice({ tab: "oversight" });
                      }}
                    >
                      Open oversight
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}
