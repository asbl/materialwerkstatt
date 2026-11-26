// Kurs-Plugin (Frontend): registriert den Workspace-Modus "kurs", den Pfad-Resolver
// für Kurs-MDX und die Ansicht "Kurse". Die eigentliche Kurs-Steuerung liegt in
// courses.js (im Plugin-Paket), der Kern stellt nur Slots und Delegation bereit.

import { createCourseController } from "./courses.js";
import { createSyncView } from "./sync-view.js";

export function register(ctx) {
  const deps = ctx.deps || {};
  const state = deps.state;
  const controller = createCourseController({ ...deps });

  const kursEntryForPath = (path) => {
    if (typeof path !== "string") return undefined;
    if (path.endsWith(".mdx") && path.startsWith("unterricht/kurse/")) {
      const slug = path.split("/")[2];
      return state.qmds.find((item) => item.kind === "Kurs (H5P)" && item.slug === slug);
    }
    return state.qmds.find((item) => item.path === path && item.kind === "Kurs (H5P)");
  };

  ctx.documents?.registerPathResolver(kursEntryForPath);

  ctx.workspace?.registerMode({
    id: "kurs",
    entryFor: (path) => kursEntryForPath(path),
    ownsDocument: (path) => typeof path === "string" && path.startsWith("unterricht/kurse/"),
    enter: (entry) => controller.openKursView(entry),
    leave: () => controller.setKursMode(false),
    actions: controller,
  });

  // Ansicht "Kurse": listet alle Kurs-Einträge aus dem Index und öffnet den Modus.
  ctx.views.register({
    id: "kurse",
    title: "Kurse",
    // Explizit das Kern-Icon: Das Plugin bringt für die Sync-Ansicht eigene Icons mit.
    iconHref: "/static/icons.svg#folder",
    order: 40,
    mount(section) {
      section.classList.add("kurse-view");
      section.innerHTML = `<header class="kurse-header"><div><h2>Kurse</h2><p class="muted">H5P-Kurse aus unterricht/kurse</p></div></header><ul class="index-list" data-kurse-list></ul>`;
      const list = section.querySelector("[data-kurse-list]");
      const render = () => {
        const kurse = state.qmds.filter((item) => item.kind === "Kurs (H5P)");
        list.replaceChildren(...kurse.map((entry) => {
          const li = document.createElement("li");
          const button = document.createElement("button");
          button.type = "button";
          button.dataset.kursPath = entry.path;
          button.innerHTML = `<span class="index-label">${deps.escapeHtml(entry.title || entry.slug)}</span>`;
          button.onclick = () => deps.selectDocument?.(entry.path);
          li.append(button);
          return li;
        }));
        if (!kurse.length) list.innerHTML = '<li class="muted">Keine Kurse vorhanden.</li>';
      };
      render();
      section._renderKurse = render;
    },
    onActivate() {
      // Index kann sich geändert haben; Liste bei Aktivierung neu rendern.
      const section = document.getElementById("viewSection-kurse");
      section?._renderKurse?.();
    },
  });

  // Ansicht "Kurs-Sync": Sync-Grad je Kurs und Plattform (lokal erfasster Stand).
  ctx.views.register({
    id: "kurse-sync",
    title: "Kurs-Sync",
    icon: "sync",
    order: 41,
    ...createSyncView({
      api: deps.api || ctx.api,
      escapeHtml: deps.escapeHtml,
      selectDocument: deps.selectDocument,
      setStatus: deps.setStatus,
    }),
  });
}
