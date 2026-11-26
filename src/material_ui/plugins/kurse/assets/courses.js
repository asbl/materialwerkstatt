export function createCourseController({ state, elements, api, clearRenderReport, clearTimers, updateDocumentUrl, saveLastDocumentPreference, hideRenderPanel, documentLabel, renderFolderNavigation, escapeHtml, confirmDiscardOrSave, setEditorText, offerDraft, flushPendingSave, setStatus, readJobStatus, showRenderPanel, openModal, closeModal, setRenderingIndicator, updateSaveIndicator, editor, flashSaveFeedback, registerTab, setWorkspaceChrome, search, documentState }) {
  function setKursMode(active) {
    state.course.kursMode = active;
    if (active) editor?.setReadOnly(false);
    elements.pdfPreview.title = active ? "Kursvorschau" : "PDF Vorschau";
    elements.folderViewButton.title = active ? "Kurs verlassen und Ordner anzeigen" : "Ordner";
    elements.tagTreeViewButton.title = active ? "Kurs verlassen und Tags anzeigen" : "Material finden";
    elements.folderNavDetails.open = !active;
    setWorkspaceChrome?.(active ? {
      className: "kurs-mode",
      hide: ["toolbar", "previewToolbar", "documentAdvanced", "documentInfo", "editorShell", "editorStatus"],
      show: ["courseToolbar", "kursPane", "kursActions", "courseActivityPane"]
    } : null);
  }

  function openKursView(entry) {
    clearRenderReport();
    flashSaveFeedback?.("clear");
    if (documentState) documentState.begin();
    else { state.session += 1; state.documentLoad += 1; }
    state.revision = null;
    state.lastWrittenText = null;
    state.renderJob = null;
    state.course.auditJob = null;
    state.course.moodleJob = null;
    clearTimers();
    state.qmdPath = entry.path;
    registerTab?.(entry.path);
    updateDocumentUrl(entry.path);
    saveLastDocumentPreference(entry.path);
    state.course.kursSlug = entry.slug;
    state.course.kursPreviewChapter = null;
    state.course.kursPreviewActivity = null;
    state.course.kursActivity = null;
    state.course.kursIndex = entry.chapterList || [];
    state.dirty = false;
    updateSaveIndicator();
    if (search) search.displayDocument(documentLabel(entry));
    else if (state.navigationView !== "tagTree") elements.documentSearch.value = documentLabel(entry);
    hideRenderPanel();
    setKursMode(true);
    elements.kursTitle.textContent = entry.title || entry.slug;
    elements.kursSlugValue.textContent = entry.slug;
    elements.kursChapters.textContent = entry.chapters === undefined || entry.chapters === null ? "-" : String(entry.chapters);
    elements.kursPath.textContent = entry.path;
    elements.kursPreviewStatus.textContent = "Noch keine Vorschau gestartet.";
    elements.kursPreviewStopBtn.hidden = true;
    elements.kursChapterList.innerHTML = kursChapterListHtml(entry.chapterList || []);
    elements.saveCourseActivity.disabled = true;
    elements.reloadCourseActivity.disabled = true;
    elements.courseActivityTitle.textContent = "Aktivität bearbeiten";
    elements.courseActivityHint.hidden = false;
    renderFolderNavigation(entry.path.split("/").slice(0, -1).join("/"));
    loadKursIndex(entry.slug);
    elements.moodleChapterSelect.innerHTML = moodleChapterOptionsHtml(entry.chapterList || []);
    elements.moodleTarget.value = "";
    renderMoodleTargetOptions(entry.moodleTargets || []);
    showKursPreviewMessage("Kapitel auswählen oder „Vorschau starten“ anklicken, um die Kursvorschau zu öffnen.");
    setStatus(`Kurs geladen: ${entry.slug}`, "ready");
    pollKursPreview();
  }

  // Bekannte Ziele des Kurses als Vorschlaege im Zielfeld; neue Ziele legt die Ansicht
  // "Kurs-Sync" an.
  function renderMoodleTargetOptions(targets) {
    if (!elements.moodleTargetList) return;
    elements.moodleTargetList.innerHTML = targets.map((name) => `<option value="${escapeHtml(name)}"></option>`).join("");
  }

  function kursChapterListHtml(chapters) {
    if (!chapters.length) return "";
    return chapters.map((chapter, index) => `<li><details data-chapter="${escapeHtml(chapter.slug)}"${index === 0 ? " open" : ""}><summary title="${escapeHtml(chapter.title)}"><span class="index-label">${escapeHtml(chapter.title)}</span></summary><ul class="index-list">${(chapter.activities || []).map((activity) => `<li><button type="button" title="${escapeHtml(activity.title)}" data-chapter="${escapeHtml(chapter.slug)}" data-activity="${escapeHtml(activity.id)}" aria-current="${state.course.kursActivity?.id === activity.id}"><span class="index-label">${escapeHtml(activity.title)}</span></button></li>`).join("")}</ul></details></li>`).join("");
  }

  async function loadKursIndex(slug) {
    try {
      const data = await api(`/api/kurse/${encodeURIComponent(slug)}/index`);
      if (!state.course.kursMode || state.course.kursSlug !== slug) return;
      const expanded = new Set([...elements.kursChapterList.querySelectorAll("details[open]")].map((details) => details.dataset.chapter));
      state.course.kursIndex = data.chapters;
      elements.kursChapterList.innerHTML = kursChapterListHtml(data.chapters);
      for (const details of elements.kursChapterList.querySelectorAll("details")) details.open = expanded.has(details.dataset.chapter);
    } catch (error) {
      if (state.course.kursMode && state.course.kursSlug === slug) setStatus(`Kursindex konnte nicht geladen werden: ${error.message}`, "error");
    }
  }

  async function openKursActivity(chapter, identifier) {
    const slug = state.course.kursSlug;
    if (!(await confirmDiscardOrSave())) return;
    flashSaveFeedback?.("clear");
    const load = ++state.course.kursActivityLoad;
    const session = state.session;
    clearTimers();
    editor?.setReadOnly(true);
    try {
      const data = await api(`/api/kurse/${encodeURIComponent(slug)}/activities/${encodeURIComponent(identifier)}`);
      if (!state.course.kursMode || state.course.kursSlug !== slug || state.course.kursActivityLoad !== load || session !== state.session) return;
      state.course.kursActivity = { id: identifier, chapter, path: data.path };
      state.session += 1;
      state.revision = data.revision;
      state.lastWrittenText = data.text;
      state.dirty = false;
      updateSaveIndicator();
      setEditorText(data.text, { keepExpanded: true });
      offerDraft(data);
      elements.editorShell.hidden = false;
      elements.editorStatus.hidden = false;
      elements.courseActivityPane.hidden = true;
      elements.documentInfo.hidden = false;
      elements.documentInfo.textContent = `${data.title} · ${data.path}`;
      editor?.setAriaLabel("Aktivitätseditor");
      elements.saveCourseActivity.disabled = false;
      elements.reloadCourseActivity.disabled = false;
      const offset = Math.max(0, data.text.indexOf(`identifier="${identifier}"`));
      editor?.setSelectionRange(offset, offset);
      editor?.focus();
      await startKursPreview(chapter, identifier);
    } catch (error) {
      if (state.course.kursMode && state.course.kursSlug === slug && state.course.kursActivityLoad === load) {
        setStatus(`Aktivität konnte nicht geöffnet werden: ${error.message}`, "error");
      }
    } finally {
      if (state.course.kursMode && state.course.kursSlug === slug && state.course.kursActivityLoad === load) {
        editor?.setReadOnly(false);
      }
    }
  }

  function refreshCourseActivityPreview() {
    if (!state.course.kursActivity) return;
    startKursPreview(state.course.kursActivity.chapter, state.course.kursActivity.id);
  }

  async function saveAndRefreshCourseActivity() {
    try {
      await flushPendingSave();
      refreshCourseActivityPreview();
      flashSaveFeedback?.("ok", "Gespeichert");
    } catch (error) {
      flashSaveFeedback?.("error", "Speichern fehlgeschlagen");
      setStatus(`Speichern fehlgeschlagen: ${error.message}`, "error");
    }
  }

  async function startKursAudit() {
    if (!state.course.kursSlug) return;
    const session = state.session;
    await flushPendingSave();
    if (session !== state.session || !state.course.kursMode) return;
    if (state.course.kursAuditPollTimer) clearTimeout(state.course.kursAuditPollTimer);
    setStatus("Audit läuft …", "rendering");
    const slug = state.course.kursSlug;
    const data = await api(`/api/kurse/${encodeURIComponent(slug)}/audit`, { method: "POST" });
    if (!state.course.kursMode || state.course.kursSlug !== slug) return;
    state.course.auditJob = data.job_id;
    pollKursAudit();
  }

  async function pollKursAudit() {
    if (state.course.kursAuditPollTimer) clearTimeout(state.course.kursAuditPollTimer);
    const session = state.session;
    const job = state.course.auditJob;
    const data = await readJobStatus(state.course.auditJob ? `/api/jobs/${state.course.auditJob}` : `/api/kurse/${encodeURIComponent(state.course.kursSlug)}/audit/status`, "kursAuditPollTimer", pollKursAudit);
    if (!data || job !== state.course.auditJob) return;
    if (session !== state.session || !state.course.kursMode) return;
    setStatus(data.message || "Audit läuft …", data.ok === false ? "error" : data.running ? "rendering" : "ok");
    if (data.detail) showRenderPanel(data.detail, data.running ? "Audit läuft …" : (data.message || "Audit abgeschlossen"));
    if (data.running) state.course.kursAuditPollTimer = setTimeout(pollKursAudit, 900);
  }

  function moodleChapterOptionsHtml(chapters) {
    if (!chapters.length) return '<option value="">Keine Kapitel</option>';
    return chapters.map((chapter) => `<option value="${escapeHtml(chapter.slug)}">${escapeHtml(chapter.title)}</option>`).join("");
  }

  function openMoodleConfirm(operation, extraPayload = {}) {
    if (!state.course.kursSlug) return;
    elements.moodleConfirmText.textContent = moodleConfirmText(operation, extraPayload);
    state.course.pendingMoodleAction = () => {
      closeMoodleConfirmModal();
      startKursMoodleJob(operation, extraPayload);
    };
    elements.moodleConfirmBtn.onclick = state.course.pendingMoodleAction;
    openModal(elements.moodleConfirmModal, elements.moodleConfirmCancelBtn);
  }

  function moodleConfirmText(operation, extraPayload) {
    const target = elements.moodleTarget.value.trim();
    const targetLabel = target ? ` (Ziel: ${target})` : "";
    if (operation === "upload-chapter") {
      const chapterLabel = elements.moodleChapterSelect.selectedOptions[0]?.textContent || extraPayload.chapter || "";
      return `Kapitel „${chapterLabel}“ wirklich nach Moodle hochladen${targetLabel}?`;
    }
    if (operation === "upload-course") {
      return `Den gesamten Kurs „${state.course.kursSlug}“ wirklich nach Moodle hochladen${targetLabel}?`;
    }
    if (operation === "publish") {
      return `Kurs „${state.course.kursSlug}“ wirklich veröffentlichen${targetLabel}? Das läuft Tests, Audit, Upload und Remote-Verifikation.`;
    }
    return "Aktion wirklich ausfuehren?";
  }

  function closeMoodleConfirmModal() {
    closeModal(elements.moodleConfirmModal);
    state.course.pendingMoodleAction = null;
  }

  async function startKursMoodleJob(operation, extraPayload = {}) {
    if (!state.course.kursSlug) return;
    const session = state.session;
    await flushPendingSave();
    if (session !== state.session || !state.course.kursMode) return;
    if (state.course.kursMoodlePollTimer) clearTimeout(state.course.kursMoodlePollTimer);
    const target = elements.moodleTarget.value.trim();
    const payload = { ...extraPayload };
    if (target) payload.target = target;
    setStatus("Moodle-Aktion läuft …", "rendering");
    const slug = state.course.kursSlug;
    const data = await api(`/api/kurse/${encodeURIComponent(slug)}/moodle/${operation}`, {
      method: "POST",
      body: JSON.stringify(payload)
    });
    if (!state.course.kursMode || state.course.kursSlug !== slug) return;
    state.course.moodleJob = data.job_id;
    pollKursMoodleJob();
  }

  async function pollKursMoodleJob() {
    if (state.course.kursMoodlePollTimer) clearTimeout(state.course.kursMoodlePollTimer);
    const session = state.session;
    const job = state.course.moodleJob;
    const data = await readJobStatus(state.course.moodleJob ? `/api/jobs/${state.course.moodleJob}` : `/api/kurse/${encodeURIComponent(state.course.kursSlug)}/moodle/status`, "kursMoodlePollTimer", pollKursMoodleJob);
    if (!data || job !== state.course.moodleJob) return;
    if (session !== state.session || !state.course.kursMode) return;
    setStatus(data.message || "Moodle-Aktion läuft …", data.ok === false ? "error" : data.running ? "rendering" : "ok");
    if (data.detail) showRenderPanel(data.detail, data.running ? "Moodle-Aktion läuft …" : (data.message || "Moodle-Aktion abgeschlossen"));
    if (data.running) state.course.kursMoodlePollTimer = setTimeout(pollKursMoodleJob, 900);
  }

  async function startKursPreview(chapter = null, activity = null) {
    if (!state.course.kursMode || !state.course.kursSlug) return;
    const courseSlug = state.course.kursSlug;
    state.course.kursPreviewChapter = chapter;
    state.course.kursPreviewActivity = activity;
    elements.courseActivityTitle.textContent = activity
      ? state.course.kursIndex.flatMap((item) => item.activities || []).find((item) => item.id === activity)?.title || activity
      : "Aktivität bearbeiten";
    for (const button of elements.kursChapterList.querySelectorAll("button[data-activity]")) {
      button.setAttribute("aria-current", String(button.dataset.activity === state.course.kursActivity?.id));
    }
    if (state.course.kursPreviewPollTimer) clearTimeout(state.course.kursPreviewPollTimer);
    elements.kursPreviewStatus.textContent = "Vorschau wird vorbereitet …";
    showKursPreviewMessage("Kursvorschau wird vorbereitet …");
    elements.kursPreviewStopBtn.hidden = false;
    try {
      await api(`/api/kurse/${encodeURIComponent(courseSlug)}/preview`, { method: "POST" });
      if (state.course.kursMode && state.course.kursSlug === courseSlug) await pollKursPreview();
    } catch (error) {
      if (state.course.kursMode && state.course.kursSlug === courseSlug) showKursPreviewError(error);
    }
  }

  async function stopKursPreview() {
    if (state.course.kursPreviewPollTimer) clearTimeout(state.course.kursPreviewPollTimer);
    await api("/api/kurse/preview/stop", { method: "POST" });
    elements.kursPreviewStopBtn.hidden = true;
    elements.kursPreviewStatus.textContent = "Vorschau beendet.";
    showKursPreviewMessage("Kursvorschau beendet. Ein Kapitel auswählen, um sie erneut zu starten.");
  }

  async function pollKursPreview() {
    if (!state.course.kursMode) return;
    const courseSlug = state.course.kursSlug;
    if (state.course.kursPreviewPollTimer) clearTimeout(state.course.kursPreviewPollTimer);
    let data;
    try {
      data = await readJobStatus("/api/kurse/preview/status", "kursPreviewPollTimer", pollKursPreview);
      if (!data) return;
    } catch (error) {
      if (state.course.kursMode && state.course.kursSlug === courseSlug) showKursPreviewError(error);
      return;
    }
    if (!state.course.kursMode || state.course.kursSlug !== courseSlug) return;
    if (data.slug !== state.course.kursSlug) {
      // Vorschau laeuft (oder lief) fuer einen anderen Kurs -- fuer diese Ansicht nicht relevant.
      elements.kursPreviewStopBtn.hidden = true;
      return;
    }
    if (!data.running) {
      elements.kursPreviewStopBtn.hidden = true;
      elements.kursPreviewStatus.textContent = data.error
        ? `Vorschau fehlgeschlagen:\n${data.error}`
        : "Vorschau-Prozess ist beendet. Bitte erneut starten.";
      showKursPreviewMessage(elements.kursPreviewStatus.textContent);
      return;
    }
    elements.kursPreviewStopBtn.hidden = false;
    if (data.ready) {
      elements.kursPreviewStatus.textContent = `Vorschau läuft: ${data.url}`;
      showKursPreview(data.url);
      return;
    }
    elements.kursPreviewStatus.textContent = "Vorschau wird vorbereitet …";
    state.course.kursPreviewPollTimer = setTimeout(pollKursPreview, 2000);
  }

  function showKursPreviewMessage(message) {
    state.loadedPdf = "";
    elements.pdfPreview.removeAttribute("src");
    setRenderingIndicator(false);
    elements.pdfEmptyState.textContent = message;
    elements.pdfEmptyState.hidden = false;
  }

  function showKursPreviewError(error) {
    const message = `Kursvorschau fehlgeschlagen: ${error.message}`;
    elements.kursPreviewStatus.textContent = message;
    elements.kursPreviewStopBtn.hidden = true;
    showKursPreviewMessage(message);
    setStatus(message, "error");
  }

  function showKursPreview(url) {
    state.loadedPdf = "";
    elements.pdfEmptyState.hidden = true;
    const previewUrl = new URL(url);
    if (state.course.kursPreviewActivity) {
      const activityPath = `/preview/${encodeURIComponent(state.course.kursSlug)}/${encodeURIComponent(state.course.kursPreviewActivity)}`;
      previewUrl.pathname = activityPath;
      previewUrl.search = "mode=view&simple=1";
    }
    if (state.course.kursPreviewChapter !== null) previewUrl.hash = new URLSearchParams({ chapter: state.course.kursPreviewChapter }).toString();
    if (elements.pdfPreview.src !== previewUrl.href) elements.pdfPreview.src = previewUrl.href;
  }

  return { setKursMode, openKursView, kursChapterListHtml, loadKursIndex, openKursActivity, refreshCourseActivityPreview, saveAndRefreshCourseActivity, startKursAudit, pollKursAudit, moodleChapterOptionsHtml, openMoodleConfirm, moodleConfirmText, closeMoodleConfirmModal, startKursMoodleJob, pollKursMoodleJob, startKursPreview, stopKursPreview, pollKursPreview, showKursPreviewMessage, showKursPreviewError, showKursPreview };
}
