import { useEffect, useRef } from "react";

// One focus contract for existing dialogs. Only the topmost dialog handles keys.
export function useDialogFocus(onClose?: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    const previous = document.activeElement;
    const focusables = () => Array.from(root.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), select, textarea, a[href], [tabindex="0"]',
    )).filter((el) => el.getClientRects().length > 0);
    (focusables()[0] ?? root).focus();
    const key = (event: KeyboardEvent) => {
      const dialogs = document.querySelectorAll('[aria-modal="true"]');
      if (dialogs[dialogs.length - 1] !== root) return;
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        closeRef.current?.();
      }
      if (event.key === "Tab") {
        const items = focusables();
        const index = items.indexOf(document.activeElement as HTMLElement);
        if (!items.length || index < 0 || (!event.shiftKey && index === items.length - 1) ||
            (event.shiftKey && index === 0)) {
          event.preventDefault();
          (event.shiftKey ? items.at(-1) ?? root : items[0] ?? root).focus();
        }
      }
    };
    document.addEventListener("keydown", key, true);
    return () => {
      document.removeEventListener("keydown", key, true);
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, []);
  return ref;
}
