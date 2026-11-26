export function createGitController({ state, elements, api, openModal, closeModal, flushPendingSave, setStatus }) {
  async function openGitModal() {
    if (state.course.kursMode || !state.qmdPath) return;
    await flushPendingSave();
    const modal = document.getElementById("gitModal");
    openModal(modal, document.getElementById("refreshGit"));
    await refreshGit();
  }

  function closeGitModal() {
    closeModal(document.getElementById("gitModal"));
  }

  async function refreshGit() {
    if (!state.qmdPath) return;
    const hint = document.getElementById("gitHint");
    const button = document.getElementById("refreshGit");
    button.disabled = true;
    hint.textContent = "Git-Status wird gelesen …";
    try {
      const data = await api(`/api/document/git?path=${encodeURIComponent(state.qmdPath)}`);
      if (!data.available) {
        document.getElementById("gitPath").textContent = state.qmdPath;
        document.getElementById("gitStatus").textContent = "-";
        document.getElementById("gitLastCommit").textContent = "-";
        document.getElementById("gitDiff").textContent = "";
        hint.textContent = data.reason || "Kein Git-Repository gefunden.";
        return;
      }
      document.getElementById("gitPath").textContent = data.path;
      document.getElementById("gitStatus").textContent = data.changed
        ? `${data.status || "geändert"}`
        : "Unverändert gegenüber dem letzten Commit.";
      document.getElementById("gitLastCommit").textContent = data.last_commit || "Noch kein Commit für diese Datei.";
      document.getElementById("gitDiff").textContent = data.diff || "";
      hint.textContent = data.diff_truncated ? "Diff wurde nach 64 KiB gekürzt." : "";
    } catch (error) {
      hint.textContent = `Git-Status fehlgeschlagen: ${error.message}`;
      setStatus(`Git-Status fehlgeschlagen: ${error.message}`, "error");
    } finally {
      button.disabled = false;
    }
  }

  return { openGitModal, closeGitModal, refreshGit };
}
