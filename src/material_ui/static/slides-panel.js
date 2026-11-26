import { waitForJob } from "./job-client.js";

export function createSlidesController({ api, button, getDocument, flush, setStatus, openDeck }) {
  async function playSlides() {
    const document = getDocument();
    if (!document) return;
    button.disabled = true;
    const current = () => getDocument()?.session === document.session;
    try {
      await flush();
      if (!current()) return;
      const { job_id } = await api("/api/slides/ensure", {
        method: "POST", body: JSON.stringify({ path: document.path })
      });
      const result = await waitForJob(api, job_id);
      if (!current()) return;
      setStatus(result.generated ? "Präsentation erzeugt." : "Präsentation wird abgespielt.", "ok");
      openDeck(result.deck);
    } catch (error) {
      if (current()) setStatus(`Präsentation fehlgeschlagen: ${error.message}`, "error");
    } finally {
      button.disabled = false;
    }
  }
  return { playSlides };
}
