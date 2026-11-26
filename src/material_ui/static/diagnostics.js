// Generated TeX/Typst lines do not refer to the QMD source and must not be
// positioned in the editor without a source map.
export function renderDiagnostics(detail, path) {
  const escape = value => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const reference = new RegExp(`(?:^|[\\s(])(${escape(path)}|${escape(path.split("/").pop())}|[^\\s:]*material-ui-render-[^\\s:]+\\.qmd):(\\d+)(?::(\\d+))?`);
  return String(detail?.log || "").split("\n").flatMap(line => {
    const match = line.match(reference);
    if (!match) return [];
    const name = match[1];
    if (name !== path && name !== path.split("/").pop() && !name.split("/").pop().startsWith("material-ui-render-")) return [];
    return [{ level: /warning|warnung/i.test(line) ? "warning" : "error", title: "Render-Hinweis", detail: line.trim(), line: Number(match[2]), column: Number(match[3]) || 1 }];
  });
}

export function createDiagnosticsController({ state, api, editor, setStatus }) {
  const panel = document.getElementById("editorDiagnostics");
  const summary = document.getElementById("diagnosticsSummary");
  const list = document.getElementById("diagnosticsList");
  let timer = null;
  let request = null;
  let generation = 0;
  let checks = [];
  let renderIssues = [];
  let languageIssues = [];
  const languageStatus = document.getElementById("languageCheckStatus");

  function display() {
    const unique = new Map([...checks, ...renderIssues, ...languageIssues].filter(issue => issue.level !== "ok")
      .map(issue => [JSON.stringify([issue.target, issue.code, issue.page, issue.line, issue.title, issue.detail]), issue]));
    const issues = [...unique.values()];
    editor.setDiagnostics(issues.filter(issue => issue.line));
    panel.hidden = issues.length === 0;
    summary.textContent = `${issues.length} Prüfhinweis${issues.length === 1 ? "" : "e"}`;
    list.replaceChildren(...issues.map(issue => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = `diagnostic-item diagnostic-${issue.level}`;
      button.textContent = `${issue.line ? `Zeile ${issue.line}: ` : ""}${issue.title} – ${issue.detail}`;
      button.addEventListener("click", () => {
        if (issue.target === "pdf" && issue.page) {
          const preview = document.getElementById("pdfPreview");
          if (preview?.getAttribute("src")) {
            const url = new URL(preview.src, window.location.href);
            url.hash = `page=${issue.page}&toolbar=0&navpanes=0`;
            preview.src = url.href;
          }
        } else if (issue.line) {
          editor.jumpToLine(issue.line);
          editor.focus();
        } else {
          setStatus(issue.detail, "ready");
        }
      });
      item.append(button);
      return item;
    }));
  }

  function cancel() {
    generation += 1;
    if (timer) clearTimeout(timer);
    timer = null;
    request?.abort();
    request = null;
  }

  async function check({ explicit = false, beforeRender = false } = {}) {
    // Background diagnostics may be rescheduled while preflight is in flight.
    // They must never abort the check that gates a render start.
    if (!beforeRender) cancel();
    const path = state.qmdPath;
    if (state.course.kursMode || !(/\.(qmd|md)$/i.test(path))) return false;
    const text = editor.getEditorText();
    const session = state.session;
    const load = generation;
    const controller = new AbortController();
    if (!beforeRender) request = controller;
    try {
      const [data, language] = await Promise.all([
        api("/api/check", { method: "POST", body: JSON.stringify({ path, text }), signal: controller.signal }),
        beforeRender ? Promise.resolve(null) : api("/api/document/language-check", {
          method: "POST", body: JSON.stringify({path, text}), signal: controller.signal
        }).catch(() => ({issues: [], status: "Grammatikprüfung nicht verfügbar"}))
      ]);
      if ((!beforeRender && load !== generation) || path !== state.qmdPath || session !== state.session || text !== editor.getEditorText()) return false;
      checks = data.issues || [];
      if (language) {
        languageIssues = language.issues || [];
        if (languageStatus) languageStatus.textContent = `Rechtschreibung: Browser · ${language.status}`;
      }
      display();
      const blocked = checks.some(issue => issue.level === "error");
      if (beforeRender && blocked) {
        panel.open = true;
        setStatus("Rendern gesperrt: Bitte zuerst die Fehler der Vorprüfung beheben.", "error");
      } else if (explicit) {
        panel.open = true;
        setStatus(checks.some(issue => ["error", "warning"].includes(issue.level)) ? "Prüfung mit Hinweisen abgeschlossen." : "Prüfung ohne Auffälligkeiten.", "ready");
      }
      return !blocked;
    } catch (error) {
      if ((explicit || beforeRender) && (beforeRender || load === generation) && path === state.qmdPath && session === state.session && !controller.signal.aborted) setStatus(`Prüfung fehlgeschlagen: ${error.message}`, "error");
      return false;
    } finally {
      if (request === controller) request = null;
    }
  }

  function schedule() {
    cancel();
    checks = [];
    renderIssues = [];
    languageIssues = [];
    display();
    if (!state.course.kursMode && /\.(qmd|md)$/i.test(state.qmdPath)) timer = setTimeout(() => check(), 600);
  }

  function updateRender(data) {
    if (state.course.kursMode || state.dirty || data.current !== state.qmdPath) return;
    const revision = data.detail?.source_revision;
    if (revision && revision !== state.revision) return;
    if (data.running) return;
    renderIssues = [...renderDiagnostics(data.detail, state.qmdPath), ...(data.detail?.layout_issues || []), ...(data.detail?.preflight_issues || [])];
    display();
    if (data.detail?.preflight_issues) panel.open = true;
    // Successful renders can remove an earlier "PDF fehlt/veraltet" warning.
    check();
  }

  function rejectRender(issues) {
    checks = issues || [];
    display();
    panel.open = true;
    setStatus("Rendern gesperrt: Bitte zuerst die Fehler der Vorprüfung beheben.", "error");
  }

  return { schedule, check, updateRender, rejectRender };
}
