// Einstellungen, Reiter „Ordner“: Inhaltsordner dieses Rechners, getrennt vom Programm.

const STATES = {
  default: ["Standardordner", "disabled"],
  active: ["eigener Ordner", "loaded"],
  restart: ["Neustart nötig", "restart-pending"],
  missing: ["Ordner fehlt", "error"]
};

export function createWorkspaceSettings({ api, restartServer }) {
  const byId = id => document.getElementById(id);
  const input = byId("workspacePath");
  const status = byId("workspaceStatus");
  let dirty = false;

  function render(data) {
    const [label, tone] = STATES[data.state] || [data.state, "disabled"];
    byId("workspaceState").textContent = label;
    byId("workspaceState").className = `plugin-badge plugin-status-${tone}`;
    input.value = data.path;
    byId("workspaceDefault").textContent = data.default;
    input.disabled = byId("workspaceSave").disabled = data.fixed;
    byId("workspaceCode").textContent = data.code;
    byId("workspaceCurrent").textContent = data.current;
    byId("workspaceRestartBanner").hidden = data.state !== "restart";
    dirty = false;
    if (data.fixed) status.textContent = "Durch die Umgebungsvariable MATERIAL_HOME festgelegt.";
  }

  async function load() {
    // Ungespeicherte Eingaben beim erneuten Öffnen nicht überschreiben.
    if (dirty) return;
    status.textContent = "";
    try {
      render(await api("/api/settings/workspace"));
    } catch (error) {
      status.textContent = error.message;
    }
  }

  input.addEventListener("input", () => { dirty = true; status.textContent = "Noch nicht gespeichert."; });
  byId("workspaceRestart").addEventListener("click", () => restartServer());
  byId("workspaceForm").addEventListener("submit", async event => {
    event.preventDefault();
    byId("workspaceSave").disabled = true;
    try {
      const data = await api("/api/settings/workspace", {
        method: "PUT", timeout: 120000,
        body: JSON.stringify({ path: input.value.trim(), create: byId("workspaceCreate").checked })
      });
      render(data);
      status.textContent = data.message;
    } catch (error) {
      status.textContent = error.message;
    } finally {
      byId("workspaceSave").disabled = false;
    }
  });

  return { load };
}
