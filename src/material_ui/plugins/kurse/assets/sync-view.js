// Ansicht "Kurs-Sync": zeigt je Kurs und Plattform, welcher Anteil der Aktivitäten
// dort liegt und ob er dem lokalen Stand entspricht. Datengrundlage ist
// /api/kurse/sync-overview (rein lokal erfasster Stand, kein Remote-Zugriff).

// Reihenfolge = Reihenfolge der Segmente im Balken und der Einträge in der Legende.
const STATUSES = [
  { id: "synced", label: "aktuell", one: "aktuell", many: "aktuell" },
  { id: "changed", label: "lokal geändert", one: "lokal geändert", many: "lokal geändert" },
  { id: "unknown", label: "vorhanden, Stand nicht erfasst", one: "ohne erfassten Stand", many: "ohne erfassten Stand" },
  { id: "missing", label: "fehlt", one: "fehlt", many: "fehlen" },
];
const STATUS_LABEL = {
  synced: "aktuell",
  changed: "lokal geändert",
  unknown: "vorhanden, Stand nicht erfasst",
  missing: "fehlt",
  excluded: "vom Kurs-Sync ausgenommen",
};

function formatDate(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" });
}

function countBy(statuses) {
  const counts = { synced: 0, changed: 0, unknown: 0, missing: 0, excluded: 0 };
  for (const status of statuses) counts[status] = (counts[status] || 0) + 1;
  return counts;
}

function countsText(counts) {
  return STATUSES
    .filter((status) => counts[status.id] > 0)
    .map((status) => `${counts[status.id]} ${counts[status.id] === 1 ? status.one : status.many}`);
}

export function createSyncView({ api, escapeHtml, selectDocument, setStatus }) {
  let section = null;
  let loadToken = 0;
  // Aufgeklappte Kurse und Kapitel über ein Neuladen hinweg merken.
  const openCourses = new Set();
  const openChapters = new Set();

  function bar(counts, { className = "ksync-bar", label, title = "" }) {
    const segments = STATUSES
      .filter((status) => counts[status.id] > 0)
      .map((status) => `<span class="ksync-seg ksync-${status.id}" style="flex-grow:${counts[status.id]}" title="${escapeHtml(`${counts[status.id]} ${status.label}`)}"></span>`)
      .join("");
    return `<div class="${className}" role="img" aria-label="${escapeHtml(label)}"${title ? ` title="${escapeHtml(title)}"` : ""}>${segments || '<span class="ksync-seg ksync-none"></span>'}</div>`;
  }

  function platformHtml(course, platform) {
    const safeUrl = /^https?:\/\//.test(platform.url || "") ? platform.url : "";
    const host = platform.host
      ? (safeUrl
        ? `<a class="ksync-host" href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener noreferrer" title="Kurs auf der Plattform öffnen">${escapeHtml(platform.host)}</a>`
        : `<span class="ksync-host">${escapeHtml(platform.host)}</span>`)
      : "";
    const notes = countsText(platform.counts);
    if (platform.excluded) notes.push(`${platform.excluded} ausgenommen`);
    if (platform.remoteOnly) notes.push(`${platform.remoteOnly} nur auf der Plattform`);
    const updated = formatDate(platform.updatedAt);
    const summary = `${platform.label}: ${notes.join(", ") || "keine Aktivitäten vorgesehen"}`;
    const degree = platform.total
      ? `<span class="ksync-degree"><strong>${platform.percent} %</strong> ${platform.tracked ? "aktuell" : "vorhanden"}</span>`
      : '<span class="ksync-degree muted">–</span>';
    return `<div class="ksync-platform">
      <div class="ksync-platform-head"><span class="ksync-platform-label">${escapeHtml(platform.label)}</span>${degree}</div>
      ${platform.target ? `<button type="button" class="ksync-link" data-target-edit="${escapeHtml(platform.target)}" data-course-slug="${escapeHtml(course.slug)}" title="URL und Zugangsdaten dieses Ziels ändern">Ziel bearbeiten</button>` : ""}
      ${host}
      ${bar(platform.counts, { label: summary })}
      <p class="ksync-note">${escapeHtml(notes.join(" · ") || "Keine Aktivitäten vorgesehen")}${updated ? `<span class="ksync-updated" title="Zeitpunkt der letzten Änderung des lokal gespeicherten Sync-Stands"> · Aufzeichnung vom ${escapeHtml(updated)}</span>` : ""}</p>
    </div>`;
  }

  function cell(status, title) {
    return `<span class="ksync-cell ksync-${status}" title="${escapeHtml(title)}"><span class="visually-hidden">${escapeHtml(title)}</span></span>`;
  }

  function chapterHtml(course, chapter, index) {
    const key = `${course.slug}/${chapter.slug}`;
    const bars = course.platforms.map((platform) => {
      const statuses = platform.chapters[index]?.statuses || [];
      const counts = countBy(statuses);
      const parts = countsText(counts);
      if (counts.excluded) parts.push(`${counts.excluded} ausgenommen`);
      const label = `${platform.label}: ${parts.join(", ") || "keine Aktivitäten"}`;
      if (counts.excluded && counts.excluded === statuses.length) {
        return `<span class="ksync-mini ksync-mini-excluded" role="img" aria-label="${escapeHtml(label)}" title="${escapeHtml(label)}"></span>`;
      }
      return bar(counts, { className: "ksync-bar ksync-mini", label, title: label });
    }).join("");
    const activities = chapter.activities.map((activity, activityIndex) => {
      const cells = course.platforms.map((platform) => {
        const status = platform.chapters[index]?.statuses[activityIndex] || "missing";
        return cell(status, `${platform.label}: ${STATUS_LABEL[status]}`);
      }).join("");
      return `<li class="ksync-row"><span class="ksync-row-title" title="${escapeHtml(activity.title)}">${escapeHtml(activity.title)}</span>${cells}</li>`;
    }).join("");
    const excluded = chapter.synced ? "" : '<span class="ksync-skip" title="Vom Kurs-Sync ausgenommen (synced={false})">⊘<span class="visually-hidden"> vom Kurs-Sync ausgenommen</span></span>';
    return `<li><details data-chapter-key="${escapeHtml(key)}"${openChapters.has(key) ? " open" : ""}>
      <summary class="ksync-row${chapter.synced ? "" : " ksync-row-skipped"}"><span class="ksync-row-title" title="${escapeHtml(chapter.title)}"><span class="ksync-row-text">${escapeHtml(chapter.title)}</span>${excluded}</span>${bars}</summary>
      <ul class="ksync-activities">${activities || '<li class="muted">Keine Aktivitäten.</li>'}</ul>
    </details></li>`;
  }

  function courseHtml(course) {
    const title = `<button type="button" class="ksync-course-title" data-course-path="${escapeHtml(course.path)}" title="Kurs öffnen">${escapeHtml(course.title)}</button>`;
    const meta = `<span class="ksync-course-meta">${course.activities} ${course.activities === 1 ? "Aktivität" : "Aktivitäten"}</span>`;
    if (course.error) {
      return `<article class="ksync-course"><header>${title}</header><p class="ksync-error">Kurs konnte nicht ausgewertet werden: ${escapeHtml(course.error)}</p></article>`;
    }
    const platforms = course.platforms.length
      ? course.platforms.map((platform) => platformHtml(course, platform)).join("")
      : '<p class="ksync-note">Noch für keine Plattform eingerichtet.</p>';
    const columns = course.platforms.map((platform) => `<span class="ksync-col" title="${escapeHtml(platform.label)}">${escapeHtml(platform.kind === "website" ? "Web" : (platform.target || "Moodle"))}</span>`).join("");
    const chapters = course.platforms.length && course.chapters.length
      ? `<details class="ksync-chapters" data-course-key="${escapeHtml(course.slug)}"${openCourses.has(course.slug) ? " open" : ""} style="--ksync-cols:${course.platforms.length}">
          <summary>Kapitel im Einzelnen</summary>
          <div class="ksync-row ksync-cols" aria-hidden="true"><span class="ksync-row-title"></span>${columns}</div>
          <ul class="ksync-chapter-list">${course.chapters.map((chapter, index) => chapterHtml(course, chapter, index)).join("")}</ul>
          ${course.chapters.some((chapter) => !chapter.synced) ? '<p class="ksync-note"><span class="ksync-skip">⊘</span> Kapitel ist vom Hochladen des ganzen Kurses ausgenommen und zählt bei Moodle nur mit, soweit es dort liegt.</p>' : ""}
        </details>`
      : "";
    const addTarget = `<div class="ksync-target-actions"><button type="button" class="ksync-link" data-target-add="${escapeHtml(course.slug)}" title="Den Kurs gegen einen weiteren Moodle-Kurs synchronisieren">+ Moodle-Ziel hinzufügen</button></div>
      <div class="ksync-target-slot" data-target-slot="${escapeHtml(course.slug)}"></div>`;
    return `<article class="ksync-course"><header>${title}${meta}</header>${platforms}${addTarget}${chapters}</article>`;
  }

  // -- Moodle-Ziele anlegen und bearbeiten ---------------------------------------

  function targetSlot(slug) {
    return [...section.querySelectorAll("[data-target-slot]")].find((slot) => slot.dataset.targetSlot === slug) || null;
  }

  function closeTargetForms() {
    section.querySelectorAll("[data-target-slot]").forEach((slot) => { slot.innerHTML = ""; });
  }

  function credentialHint(existing, kind) {
    if (!existing) return "";
    const source = kind === "user" ? existing.usernameSource : existing.passwordSource;
    const key = kind === "user" ? existing.usernameKey : existing.passwordKey;
    if (source === "target") return "";
    if (source) return `übernommen aus ${source === "course" ? "den Kurs-" : "den Standard-"}Einstellungen`;
    return `nicht gesetzt (${key})`;
  }

  function targetFormHtml(slug, data, existing) {
    const editing = Boolean(existing);
    const authModes = [...data.authModes];
    if (editing && !authModes.some((mode) => mode.id === existing.auth)) authModes.push({ id: existing.auth, label: existing.auth });
    const auth = editing ? existing.auth : "credentials";
    const authOptions = authModes
      .map((mode) => `<option value="${escapeHtml(mode.id)}"${mode.id === auth ? " selected" : ""}>${escapeHtml(mode.label)}</option>`)
      .join("");
    const ownUser = editing && existing.usernameSource === "target" ? existing.username : "";
    const userPlaceholder = editing ? credentialHint(existing, "user") : "Standard-Zugangsdaten verwenden";
    const passwordPlaceholder = editing
      ? (existing.passwordSource === "target" ? "gespeichert, leer lassen = unverändert" : (credentialHint(existing, "password") || "nicht gesetzt"))
      : "Standard-Zugangsdaten verwenden";
    const envNote = editing
      ? `<p class="ksync-note">Gespeichert als <code>${escapeHtml(existing.usernameKey)}</code> und <code>${escapeHtml(existing.passwordKey)}</code> in der lokalen Datei ${escapeHtml(data.envFile)}. Das Passwort wird nie angezeigt.</p>`
      : `<p class="ksync-note">Eigene Zugangsdaten landen in der lokalen Datei ${escapeHtml(data.envFile)} (<code>MOODLE_&lt;KURS&gt;_&lt;ZIEL&gt;_USERNAME</code> und <code>…_PASSWORD</code>). Ohne Angabe gelten die Zugangsdaten des Kurses bzw. die Standard-Zugangsdaten aus der ${escapeHtml(data.envFile)}.</p>`;
    const urlNote = editing && existing.urlSource === "env"
      ? `<p class="ksync-note">Die URL steht zusätzlich in der ${escapeHtml(data.envFile)} (<code>${escapeHtml(existing.urlEnvKey)}</code>) und wird dort mitgeändert.</p>`
      : "";
    return `<form class="ksync-target-form" data-target-form data-course-slug="${escapeHtml(slug)}" data-mode="${editing ? "edit" : "create"}" data-auth="${escapeHtml(editing ? existing.auth : "")}" novalidate>
      <h4>${editing ? `Moodle-Ziel „${escapeHtml(existing.target)}“ bearbeiten` : "Neues Moodle-Ziel"}</h4>
      <label>Name des Ziels
        <input name="target" type="text" required maxlength="40" pattern="[A-Za-z0-9][A-Za-z0-9_\\-]*" placeholder="z. B. schule2" autocomplete="off" spellcheck="false" value="${escapeHtml(editing ? existing.target : "")}"${editing ? " readonly" : ""}>
      </label>
      <label>URL des Moodle-Kurses
        <input name="courseUrl" type="url" required placeholder="https://moodle.example/course/view.php?id=12" autocomplete="off" spellcheck="false" value="${escapeHtml(editing ? existing.courseUrl : "")}">
      </label>
      ${urlNote}
      <details class="ksync-advanced"${editing && !existing.passwordSet && existing.usesCredentials ? " open" : ""}>
        <summary>Erweiterte Einstellungen</summary>
        <label>Anmeldeart <select name="auth">${authOptions}</select></label>
        <label>Benutzername <input name="username" type="text" autocomplete="off" spellcheck="false" placeholder="${escapeHtml(userPlaceholder)}" value="${escapeHtml(ownUser)}"></label>
        <label>Passwort <input name="password" type="password" autocomplete="new-password" placeholder="${escapeHtml(passwordPlaceholder)}"></label>
        <label><input name="keepSecrets" type="checkbox"${editing && existing.keepSecrets ? " checked" : ""}> Secrets des Kurses (z. B. Namen aus <code>course.yml</code>) im Klartext übertragen</label>
        <p class="ksync-note">Ohne Haken werden die Secrets beim Hochladen auf dieses Ziel durch die Ersatznamen aus <code>course.yml</code> ersetzt.</p>
        ${envNote}
      </details>
      <p class="ksync-form-error" role="alert" data-target-error></p>
      <div class="ksync-form-actions">
        <button type="submit" class="primary">Speichern</button>
        <button type="button" data-target-cancel>Abbrechen</button>
      </div>
      <p class="ksync-note">Die URL steht in <code>.moodle-target-${editing ? escapeHtml(existing.target) : "&lt;ziel&gt;"}.yml</code> im Kursordner. Hochgeladen wird im Kurs unter „Moodle“ mit diesem Zielnamen.</p>
    </form>`;
  }

  async function openTargetForm(slug, targetName = "") {
    const slot = targetSlot(slug);
    if (!slot) return;
    closeTargetForms();
    slot.innerHTML = '<p class="ksync-note">Einstellungen werden geladen …</p>';
    try {
      const data = await api(`/api/kurse/${encodeURIComponent(slug)}/moodle/targets`);
      const existing = targetName ? data.targets.find((item) => item.target === targetName) : null;
      if (targetName && !existing) throw new Error(`Ziel „${targetName}“ nicht gefunden.`);
      slot.innerHTML = targetFormHtml(slug, data, existing);
      slot.querySelector(existing ? "[name=courseUrl]" : "[name=target]").focus();
    } catch (error) {
      slot.innerHTML = `<p class="ksync-error">${escapeHtml(error.message)}</p>`;
    }
  }

  async function submitTargetForm(form) {
    const slug = form.dataset.courseSlug;
    const editing = form.dataset.mode === "edit";
    const field = (name) => form.elements[name].value;
    const target = field("target").trim();
    const error = form.querySelector("[data-target-error]");
    error.textContent = "";
    const payload = { target, courseUrl: field("courseUrl").trim(), keepSecrets: form.elements.keepSecrets.checked };
    if (field("auth") !== form.dataset.auth) payload.auth = field("auth");
    if (field("username").trim()) payload.username = field("username").trim();
    if (field("password")) payload.password = field("password");
    const buttons = form.querySelectorAll("button");
    buttons.forEach((button) => { button.disabled = true; });
    try {
      await api(`/api/kurse/${encodeURIComponent(slug)}/moodle/targets${editing ? `/${encodeURIComponent(target)}` : ""}`, {
        method: editing ? "PUT" : "POST",
        body: JSON.stringify(payload),
      });
      form.elements.password.value = "";
      closeTargetForms();
      setStatus?.(`Moodle-Ziel „${target}“ gespeichert.`, "ready");
      await load({ refresh: true });
    } catch (failure) {
      error.textContent = failure.message;
      buttons.forEach((button) => { button.disabled = false; });
    }
  }

  function render(data) {
    const body = section.querySelector("[data-ksync-body]");
    if (!data.courses.length) {
      body.innerHTML = '<p class="muted">Keine Kurse vorhanden.</p>';
      return;
    }
    const legend = `<ul class="ksync-legend" aria-label="Legende">${STATUSES.map((status) => `<li><span class="ksync-cell ksync-${status.id}"></span>${escapeHtml(status.label)}</li>`).join("")}</ul>`;
    const siteHint = data.site?.available ? "" : '<p class="ksync-note">Kein Website-Export unter build/site gefunden.</p>';
    body.innerHTML = `${legend}<div class="ksync-courses">${data.courses.map(courseHtml).join("")}</div>${siteHint}
      <p class="ksync-footnote">Grundlage ist der lokal gespeicherte Upload- und Exportstand. Änderungen direkt auf der Plattform zeigt „Remote-Status prüfen“ im Kurs.</p>`;
  }

  async function load({ refresh = false } = {}) {
    if (!section) return null;
    const token = ++loadToken;
    const status = section.querySelector("[data-ksync-status]");
    const button = section.querySelector("[data-ksync-refresh]");
    status.textContent = "Sync-Stand wird ausgewertet …";
    status.classList.remove("error");
    button.disabled = true;
    try {
      const data = await api(`/api/kurse/sync-overview${refresh ? "?refresh=1" : ""}`);
      if (token !== loadToken) return data;
      render(data);
      status.textContent = "";
      return data;
    } catch (error) {
      if (token === loadToken) {
        status.textContent = `Sync-Stand konnte nicht geladen werden: ${error.message}`;
        status.classList.add("error");
      }
      throw error;
    } finally {
      if (token === loadToken) button.disabled = false;
    }
  }

  function mount(target) {
    section = target;
    section.classList.add("ksync");
    section.innerHTML = `<header class="ksync-header"><div><h2>Kurs-Sync</h2><p class="muted">Stand der H5P-Kurse je Plattform</p></div>
        <button type="button" data-ksync-refresh title="Neu auswerten">Neu auswerten</button></header>
      <p class="ksync-status" role="status" data-ksync-status></p>
      <div data-ksync-body></div>`;
    section.querySelector("[data-ksync-refresh]").addEventListener("click", () => {
      load({ refresh: true }).catch(() => {});
    });
    section.addEventListener("click", (event) => {
      const button = event.target.closest("[data-course-path]");
      if (button) selectDocument?.(button.dataset.coursePath);
      const add = event.target.closest("[data-target-add]");
      if (add) openTargetForm(add.dataset.targetAdd);
      const edit = event.target.closest("[data-target-edit]");
      if (edit) openTargetForm(edit.dataset.courseSlug, edit.dataset.targetEdit);
      if (event.target.closest("[data-target-cancel]")) closeTargetForms();
    });
    section.addEventListener("submit", (event) => {
      const form = event.target.closest("[data-target-form]");
      if (!form) return;
      event.preventDefault();
      if (form.reportValidity()) submitTargetForm(form);
    });
    // "toggle" steigt nicht auf; in der Capture-Phase am Container abgreifen.
    section.addEventListener("toggle", (event) => {
      const details = event.target;
      if (details.dataset?.courseKey) (details.open ? openCourses.add(details.dataset.courseKey) : openCourses.delete(details.dataset.courseKey));
      if (details.dataset?.chapterKey) (details.open ? openChapters.add(details.dataset.chapterKey) : openChapters.delete(details.dataset.chapterKey));
    }, true);
  }

  return {
    mount,
    onActivate: () => load().catch((error) => { setStatus?.(`Kurs-Sync: ${error.message}`, "error"); }),
    onRefresh: () => load({ refresh: true }),
  };
}
