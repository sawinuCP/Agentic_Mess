// Confirmation dialog host (UI1). Mount once in App; requests arrive via
// confirmAction() in confirm.ts.

import { useEffect, useState } from "react";

import { getPendingConfirm, settleConfirm, subscribeConfirm } from "./confirm";
import { useDialogFocus } from "./useDialogFocus";

/** Mount once (App). Shows the current request, if any. */
export function ConfirmHost() {
  const [current, setCurrent] = useState(getPendingConfirm);
  const dialogRef = useDialogFocus(current ? () => settleConfirm(false) : undefined);

  useEffect(() => subscribeConfirm(() => setCurrent(getPendingConfirm())), []);

  if (!current) return null;

  return (
    <div className="overlay">
      <div
        ref={dialogRef}
        className="dialog confirm-dialog anim-enter"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        aria-describedby={current.options.body ? "confirm-body" : undefined}
      >
        <h2 id="confirm-title" className="text-heading">{current.options.title}</h2>
        {current.options.body && (
          <p id="confirm-body" className="text-body muted">{current.options.body}</p>
        )}
        <div className="row dialog-actions">
          <button className="btn btn-small" onClick={() => settleConfirm(false)}>Cancel</button>
          <button
            className={`btn btn-small ${current.options.danger ? "btn-danger" : "btn-primary"}`}
            onClick={() => settleConfirm(true)}
          >
            {current.options.confirmLabel ?? "Confirm"}
          </button>
        </div>
      </div>
    </div>
  );
}
