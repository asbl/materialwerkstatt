const OPERATION_LABELS = {
  render: "Rendern",
  "slides-ensure": "Präsentation vorbereiten",
  "slides-rebuild": "Präsentation neu bauen",
  audit: "Kurs-Audit",
  verify: "Moodle-Status",
  "upload-chapter": "Kapitel hochladen",
  "upload-course": "Kurs hochladen",
  publish: "Veröffentlichen"
};

const STATUS_LABELS = {
  queued: "wartet",
  running: "läuft",
  succeeded: "erfolgreich",
  failed: "gescheitert"
};

export function createJobsController({ state, elements, api, openModal, closeModal, setStatus }) {
  async function refreshJobs() {
    let data;
    try {
      data = await api("/api/jobs");
    } catch (error) {
      elements.jobsStatus.textContent = `Aufträge konnten nicht geladen werden: ${error.message}`;
      return;
    }
    const jobs = data.jobs || [];
    elements.jobsStatus.textContent = jobs.length ? `${jobs.length} Aufträge` : "Noch keine Aufträge in dieser Sitzung.";
    elements.jobsList.replaceChildren(...jobs.map(jobCard));
  }

  function jobCard(job) {
    const item = document.createElement("li");
    item.className = `job-item job-item-${job.status}`;
    const title = document.createElement("span");
    title.className = "job-title";
    title.textContent = `${OPERATION_LABELS[job.operation] || job.operation} · ${job.resource || ""}`;
    const status = document.createElement("span");
    status.className = "job-status";
    status.textContent = STATUS_LABELS[job.status] || job.status;
    const time = document.createElement("span");
    time.className = "job-time";
    time.textContent = job.updated ? new Date(job.updated * 1000).toLocaleString("de-DE") : "";
    item.append(title, status, time);
    if (job.message) {
      const message = document.createElement("span");
      message.className = "job-message";
      message.textContent = job.message;
      item.append(message);
    }
    return item;
  }

  function openJobsModal() {
    openModal(elements.jobsModal, elements.refreshJobs);
    refreshJobs();
  }

  function closeJobsModal() {
    closeModal(elements.jobsModal);
  }

  return { openJobsModal, closeJobsModal, refreshJobs };
}
