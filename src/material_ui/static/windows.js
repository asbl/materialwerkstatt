const SESSION_KEY = "material-ui:window-session";
let fallbackSession = "";

function sessionIdentifier() {
  try {
    let value = sessionStorage.getItem(SESSION_KEY);
    if (!value) {
      value = crypto.randomUUID();
      sessionStorage.setItem(SESSION_KEY, value);
    }
    return value;
  } catch {
    // Ohne Sitzungsspeicher bleibt mindestens eine Kennung je Seitenaufruf,
    // damit der Herzschlag nicht dauerhaft abgelehnt wird.
    fallbackSession = fallbackSession || crypto.randomUUID();
    return fallbackSession;
  }
}

export function createWindowController({ api, onOpenPath, onOpenImport, interval = 2000 }) {
  let timer = null;
  let stopped = false;

  function announceClose() {
    const session = sessionIdentifier();
    if (!session) return;
    try {
      fetch("/api/window/close", {
        method: "POST",
        keepalive: true,
        headers: {
          "Content-Type": "application/json",
          "X-Material-Token": document.querySelector('meta[name="material-token"]')?.content || ""
        },
        body: JSON.stringify({ session })
      }).catch(() => {});
    } catch {
      return;
    }
  }

  async function heartbeat() {
    try {
      const data = await api("/api/window/heartbeat", {
        method: "POST",
        body: JSON.stringify({ session: sessionIdentifier() }),
        timeout: 5000
      });
      for (const request of data.requests || []) {
        if (request.path) onOpenPath(request.path);
        else if (request.import) onOpenImport(request.import);
      }
    } catch {
      // Server gerade nicht erreichbar: der nächste Herzschlag versucht es erneut.
    }
    if (!stopped) timer = setTimeout(heartbeat, interval);
  }

  function start() {
    window.addEventListener("pagehide", announceClose);
    heartbeat();
  }

  function stop() {
    stopped = true;
    if (timer) clearTimeout(timer);
    window.removeEventListener("pagehide", announceClose);
    announceClose();
  }

  return { start, stop };
}
