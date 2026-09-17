import { useEffect, useRef } from "react";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { getApiToken, terminalWebSocketUrl, webSocketProtocols } from "../../api/client";

export default function TerminalPane({ sessionId }: { sessionId: string }) {
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    // Defer initialization past StrictMode's setup/cleanup probe. xterm 5's
    // viewport schedules an uncancelled startup timeout when open() is called.
    let dispose: (() => void) | undefined;
    const initialize = window.setTimeout(() => {
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

    const socket = new WebSocket(terminalWebSocketUrl(sessionId), webSocketProtocols());
    socket.onclose = (event) => {
      if (event.code !== 4401) terminal.write("\r\n[terminal disconnected — create a new terminal to continue]\r\n");
      // 4401 = WS handshake rejected by the auth middleware (Wave 1 security).
      if (event.code === 4401) {
        terminal.write("\r\n\x1b[31m[terminal rejected: API authentication required]\x1b[0m\r\n");
        if (!getApiToken()) {
          terminal.write("\x1b[90m(hint: configure the API token to connect)\x1b[0m\r\n");
        }
      }
    };
    socket.onopen = () => {
      terminal.onData((data) => { if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "input", data })); });
      terminal.onResize(({ cols, rows }) =>
        { if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: "resize", cols, rows })); },
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
    // ResizeObserver callbacks can be delivered after dispose() (queued task);
    // fit() on a disposed terminal throws "reading 'dimensions'". Guard it.
    let disposed = false;
    const observer = new ResizeObserver(() => {
      if (disposed || !host.isConnected) return;
      if (host.clientWidth && host.clientHeight) onResize();
    });
    observer.observe(host);

    dispose = () => {
      disposed = true;
      observer.disconnect();
      socket.onopen = socket.onclose = socket.onmessage = null;
      socket.close();
      terminal.dispose();
    };
    }, 0);
    return () => {
      window.clearTimeout(initialize);
      dispose?.();
    };
  }, [sessionId]);

  return <div className="terminal-host" ref={hostRef} />;
}
