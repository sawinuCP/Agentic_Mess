import { useEffect, useRef } from "react";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { terminalWebSocketUrl } from "../api/client";

export default function TerminalPane({ sessionId }: { sessionId: string }) {
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    const terminal = new Terminal({
      fontFamily: "Consolas, ui-monospace, monospace",
      fontSize: 12,
      theme: {
        background: "#0d1017",
        foreground: "#d6dbe6",
        cursor: "#5b8cff",
        selectionBackground: "#2a3650",
      },
    });
    const fit = new FitAddon();
    terminal.loadAddon(fit);
    terminal.open(host);
    try {
      fit.fit();
    } catch {
      // container not measured yet; next resize will fit
    }

    const socket = new WebSocket(terminalWebSocketUrl(sessionId));
    socket.onopen = () => {
      terminal.onData((data) => socket.send(JSON.stringify({ type: "input", data })));
      terminal.onResize(({ cols, rows }) =>
        socket.send(JSON.stringify({ type: "resize", cols, rows })),
      );
      socket.send(JSON.stringify({ type: "resize", cols: terminal.cols, rows: terminal.rows }));
    };
    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data as string) as { type: string; data?: string };
        if (message.type === "output" && message.data) {
          terminal.write(message.data);
        }
        if (message.type === "exit") {
          terminal.write("\r\n\x1b[90m[process exited]\x1b[0m\r\n");
        }
      } catch {
        // ignore malformed frames
      }
    };

    const onResize = () => {
      try {
        fit.fit();
      } catch {
        // ignore
      }
    };
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      socket.close();
      terminal.dispose();
    };
  }, [sessionId]);

  return <div className="terminal-host" ref={hostRef} />;
}
