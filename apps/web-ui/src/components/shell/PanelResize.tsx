import { useRef } from "react";
import { useStore } from "../../state/store";
import { clampSize } from "../../state/layout";

export default function PanelResize({ axis }: { axis: "sidebar" | "bottom" }) {
  const size = useStore((s) => axis === "sidebar" ? s.sidebarWidth : s.panelHeight);
  const start = useRef({ position: 0, size: 0 });
  const vertical = axis === "sidebar";
  const min = vertical ? 160 : 100;
  const max = vertical ? 600 : 700;
  const update = (value: number) => useStore.getState().set(vertical
    ? { sidebarWidth: clampSize(value, min, max) }
    : { panelHeight: clampSize(value, min, max) });
  return <div role="separator" tabIndex={0} aria-label={vertical ? "Resize sidebar" : "Resize utility panel"}
    aria-orientation={vertical ? "vertical" : "horizontal"}
    aria-valuemin={min} aria-valuemax={max} aria-valuenow={size}
    className={`panel-resize resize-${axis}`}
    onPointerDown={(e) => {
      start.current = { position: vertical ? e.clientX : e.clientY, size };
      e.currentTarget.setPointerCapture(e.pointerId);
      e.preventDefault();
    }}
    onPointerMove={(e) => {
      if (!e.currentTarget.hasPointerCapture(e.pointerId)) return;
      const delta = (vertical ? e.clientX : e.clientY) - start.current.position;
      update(start.current.size + (vertical ? delta : -delta));
    }}
    onPointerUp={(e) => e.currentTarget.releasePointerCapture(e.pointerId)}
    onKeyDown={(e) => {
      const increase = vertical ? "ArrowRight" : "ArrowUp";
      const decrease = vertical ? "ArrowLeft" : "ArrowDown";
      if (![increase, decrease, "Home", "End"].includes(e.key)) return;
      e.preventDefault();
      update(e.key === "Home" ? min : e.key === "End" ? max : size + (e.key === increase ? 20 : -20));
    }} />;
}
