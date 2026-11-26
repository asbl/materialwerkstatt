const LOG_LINE_REFERENCE = /(?:^|[\s(])([\w./-]+\.(?:qmd|tex|typst|typ|md)):(\d+)(?::(\d+))?/;

export function createRenderPanelController({ state, elements, api, escapeHtml, setStatus, showPdf, jumpToLine, flushPendingSave, canRender = () => true, beforeRender = async () => true, onPreflightFailure = () => {}, onRenderStatus = () => {} }) {
  let streamHealthy = false;
  let stream = null;
  let lastRenderStatus = null;
  let statusVersion = 0;
  function setRenderingIndicator(running) {
    if (!elements.pdfRenderingOverlay) return;
    elements.pdfRenderingOverlay.hidden = !running;
  }

  function renderStartFailed(message) {
    setRenderingIndicator(false);
    if (!state.loadedPdf) elements.pdfEmptyState.textContent = message;
  }

  async function renderDocument() {
    if (state.course.kursMode || !canRender()) return;
    if (!state.qmdPath) {
      setStatus("Kein Dokument geladen. Bitte zuerst ein Material auswählen.", "ready");
      return;
    }
    const session = state.session;
    try {
      if (!await beforeRender()) {
        if (session === state.session) renderStartFailed("PDF-Vorschau konnte nicht gestartet werden. Bitte Prüfhinweise beachten und Rendern erneut starten.");
        return;
      }
      if (session !== state.session) return;
      await flushPendingSave();
    } catch (error) {
      if (session === state.session) {
        const message = `Render-Start fehlgeschlagen: ${error.message}`;
        setStatus(message, "error");
        renderStartFailed(message);
      }
      return;
    }
    if (session !== state.session) return;
    let data;
    try {
      data = await api("/api/render", {
        method: "POST",
        body: JSON.stringify({ path: state.qmdPath })
      });
    } catch (error) {
      if (session !== state.session) return;
      renderStartFailed(`PDF-Vorschau konnte nicht gestartet werden: ${error.message}`);
      if (error.issues) onPreflightFailure(error.issues);
      else setStatus(`Render-Start fehlgeschlagen: ${error.message}`, "error");
      return;
    }
    if (session !== state.session) return;
    state.renderJob = data.job_id;
    pollRender();
  }

  async function pollRender() {
    if (state.pollTimer) clearTimeout(state.pollTimer);
    state.pollTimer = null;
    const documentPath = state.qmdPath;
    const session = state.session;
    const job = state.renderJob;
    const version = statusVersion;
    const isCurrent = () => documentPath === state.qmdPath && session === state.session && job === state.renderJob;
    const data = await readJobStatus(job ? `/api/jobs/${job}` : "/api/render/status", "pollTimer", pollRender,
      () => isCurrent() && version === statusVersion);
    if (!data || !isCurrent()) return;
    let running = data.running;
    if (!applyRenderStatus(data)) {
      if (lastRenderStatus?.session !== session || lastRenderStatus.path !== documentPath || lastRenderStatus.job !== (data.job_id || job)) return;
      // A stale progress response must not stop fallback polling for a live job.
      running = lastRenderStatus.running;
    }
    if (!isCurrent()) return; // Applying a completion may have started its successor.
    if (state.pollTimer) clearTimeout(state.pollTimer);
    state.pollTimer = running ? setTimeout(pollRender, streamHealthy ? 15000 : 900) : null;
  }

  function applyRenderStatus(data) {
    if (data.current !== state.qmdPath) return false;
    if (data.job_id && state.renderJob && data.job_id !== state.renderJob) return false;
    const job = data.job_id || state.renderJob;
    if (lastRenderStatus?.session === state.session && lastRenderStatus.path === state.qmdPath && lastRenderStatus.job === job) {
      // A job ID is never restarted. A delayed poll must not undo its SSE completion,
      // even if its timestamp is missing or the server clock has moved backwards.
      if (lastRenderStatus.running === false && data.running === true) return false;
      const completing = lastRenderStatus.running === true && data.running === false;
      if (!completing && Number.isFinite(data.updated) && Number.isFinite(lastRenderStatus.updated) && data.updated < lastRenderStatus.updated) return false;
    }
    lastRenderStatus = { session: state.session, path: state.qmdPath, job, running: data.running, updated: data.updated };
    statusVersion++;
    if (data.current === state.qmdPath) {
      setStatus(data.queued ? `${data.message} Nächster Render vorgemerkt.` : data.message || "Render läuft …", data.ok === false ? "error" : data.running ? "rendering" : "ok");
      updateRenderPanel(data);
      onRenderStatus(data);
      setRenderingIndicator(data.running);
      if (!data.running && data.pdf) showPdf(data.pdf, true);
      if (!data.running && data.next_job_id) {
        state.renderJob = data.next_job_id;
        setRenderingIndicator(true);
        setStatus("Änderungen gespeichert. Nächster Render vorgemerkt.", "rendering");
        pollRender();
      }
      if (!data.running && data.ok === false && !state.loadedPdf) {
        elements.pdfEmptyState.textContent = `PDF-Vorschau fehlgeschlagen: ${data.message} Details in der Render-Ausgabe.`;
        const logButton = document.createElement("button");
        logButton.type = "button";
        logButton.textContent = "Render-Ausgabe anzeigen";
        logButton.addEventListener("click", reopenRenderPanel);
        elements.pdfEmptyState.append(document.createElement("br"), logButton);
      }
    }
    return true;
  }

  async function readJobStatus(url, timerKey, repeat, isCurrent = () => true) {
    const session = state.session;
    try {
      const data = await api(url);
      if (session !== state.session) return null;
      state.pollFailures[timerKey] = 0;
      return data;
    } catch (error) {
      if (session !== state.session || !isCurrent()) return null;
      if (error.retryable) {
        const failures = (state.pollFailures[timerKey] || 0) + 1;
        state.pollFailures[timerKey] = failures;
        const delay = Math.min(30000, 1000 * 2 ** Math.min(failures - 1, 5));
        setStatus(`Verbindung unterbrochen. Erneute Statusabfrage in ${delay / 1000} Sekunden.`, "error");
        (timerKey.startsWith("kurs") ? state.course : state)[timerKey] = setTimeout(repeat, delay);
      } else {
        setRenderingIndicator(false);
        setStatus(error.status === 404
          ? "Auftrag nicht mehr verfügbar, möglicherweise nach einem Serverneustart. Bitte Ergebnis prüfen und bei Bedarf neu starten."
          : `Statusabfrage fehlgeschlagen: ${error.message}`, "error");
      }
      return null;
    }
  }

  function initJobStream() {
    if (!window.EventSource || stream) return;
    stream = new EventSource("/api/jobs/stream");
    stream.onopen = () => {
      streamHealthy = true;
      // Reconcile after every reconnect: the server does not replay missed events.
      if (state.renderJob) pollRender();
    };
    stream.onmessage = (event) => {
      let record;
      try {
        record = JSON.parse(event.data);
      } catch {
        return;
      }
      if (!record || record.operation !== "render") return;
      if (state.renderJob && record.job_id !== state.renderJob) return;
      if (!state.renderJob && record.resource !== state.qmdPath) return;
      if (!applyRenderStatus(record)) return;
      if (!record.running && !record.next_job_id && state.pollTimer) {
        clearTimeout(state.pollTimer);
        state.pollTimer = null;
      }
    };
    stream.onerror = () => {
      streamHealthy = false;
      if (state.renderJob) pollRender();
    };
    window.addEventListener("pagehide", () => { streamHealthy = false; stream.close(); }, { once: true });
  }

  function updateRenderPanel(data) {
    const detail = data.detail;
    if (!detail) {
      if (data.ok !== false) hideRenderPanel();
      return;
    }
    state.renderReport = { detail, title: data.message || "Render-Ausgabe" };
    elements.showRenderPanel.disabled = false;
    if (data.ok === false) {
      showRenderPanel(detail, data.message || "Render fehlgeschlagen.");
    } else if (data.running && !elements.renderPanel.hidden) {
      showRenderPanel(detail, "Render läuft …");
    } else if (data.ok === true && !elements.renderPanel.hidden) {
      showRenderPanel(detail, data.message || "Render fertig.");
    }
  }

  function showRenderPanel(detail, title) {
    state.renderReport = { detail, title };
    elements.showRenderPanel.disabled = false;
    elements.renderPanel.hidden = false;
    elements.renderPanel.classList.toggle("error", detail.status === "failed");
    elements.renderPanelTitle.textContent = title;
    elements.renderSource.textContent = detail.source || "-";
    elements.renderCommand.textContent = detail.command || "-";
    elements.renderExitCode.textContent = detail.returncode === null || detail.returncode === undefined ? "-" : String(detail.returncode);
    renderWarnings(detail);
    renderLog(detail.log || "Kein Logtext vorhanden.");
  }

  function renderWarnings(detail) {
    let container = elements.renderPanel.querySelector(".render-warnings");
    const warnings = detail.warnings || [];
    if (!warnings.length) {
      container?.remove();
      return;
    }
    if (!container) {
      container = document.createElement("pre");
      container.className = "render-warnings";
      elements.renderLog.before(container);
    }
    container.textContent = `${warnings.length === 1 ? "1 Warnung" : `${warnings.length} Warnungen`} beim Rendern:\n${warnings.join("\n")}`;
  }

  function renderLog(log) {
    const lines = String(log).split("\n");
    elements.renderLog.innerHTML = lines.map((line) => {
      const escaped = escapeHtml(line);
      const match = line.match(LOG_LINE_REFERENCE);
      if (!match) return escaped;
      return escaped.replace(
        escapeHtml(match[0]),
        `<span class="log-line-ref" data-line="${Number(match[2])}" role="button" tabindex="0" title="Zur Zeile ${Number(match[2])} im Editor springen">${escapeHtml(match[0])}</span>`
      );
    }).join("\n");
  }

  function jumpToLogLine(line) {
    jumpToLine(Number(line) || 1);
  }

  function showCheckPanel(issues) {
    const hasProblem = issues.some((issue) => issue.level === "error" || issue.level === "warning");
    elements.renderPanel.hidden = false;
    elements.renderPanel.classList.toggle("error", hasProblem);
    elements.renderPanelTitle.textContent = hasProblem ? "Material-Check: Hinweise" : "Material-Check: alles gut";
    elements.renderSource.textContent = state.qmdPath || "-";
    elements.renderCommand.textContent = "material-ui check";
    elements.renderExitCode.textContent = "-";
    elements.renderPanel.querySelector(".render-warnings")?.remove();
    renderLog(issues.map((issue) => (
      `[${issue.level}] ${issue.title}\n${issue.detail}`
    )).join("\n\n"));
    setStatus(hasProblem ? "Prüfung mit Hinweisen abgeschlossen." : "Prüfung ohne Auffälligkeiten.", hasProblem ? "error" : "ok");
  }

  function hideRenderPanel() {
    elements.renderPanel.hidden = true;
    elements.renderPanel.classList.remove("error");
    elements.renderLog.textContent = "";
    elements.renderPanel.querySelector(".render-warnings")?.remove();
  }

  async function reopenRenderPanel() {
    if (!state.renderReport) {
      // Kein Report in dieser Sitzung: letzten Render-Stand vom Server holen.
      let detail;
      let title = "Render-Ausgabe";
      try {
        const data = await api("/api/render/status");
        title = data?.message || title;
        detail = data?.detail || {
          status: data?.ok === false ? "failed" : "ok",
          source: data?.current || "-",
          command: "-",
          returncode: null,
          log: data?.message || "Noch keine Render-Ausgabe vorhanden."
        };
      } catch (error) {
        detail = { status: "failed", source: "-", command: "-", returncode: null, log: `Statusabfrage fehlgeschlagen: ${error.message}` };
      }
      state.renderReport = { detail, title };
      elements.showRenderPanel.disabled = false;
    }
    showRenderPanel(state.renderReport.detail, state.renderReport.title);
    elements.renderPanel.scrollIntoView({ block: "nearest" });
  }

  function clearRenderReport() {
    state.renderReport = null;
    elements.showRenderPanel.disabled = true;
  }

  return {
    setRenderingIndicator, renderDocument, pollRender, applyRenderStatus, readJobStatus,
    initJobStream, updateRenderPanel, showRenderPanel, showCheckPanel, hideRenderPanel,
    reopenRenderPanel, clearRenderReport, jumpToLogLine
  };
}
