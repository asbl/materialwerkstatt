// Publication controls are loaded only when the Lernstand plugin is enabled.
export function register(ctx) {
  ctx.units.registerAction({
    id: 'lernstand-export',
    matches: unit => Boolean(unit.data.lernstand),
    mount({ unit, container }) {
      const api = ctx.api;
      const solutionOption = document.createElement('label'), includeSolutions = document.createElement('input');
      includeSolutions.type = 'checkbox';
      solutionOption.append(includeSolutions, document.createTextNode('Freigegebene Lösungen einschließen'));
      const exportButton = document.createElement('button'); exportButton.type = 'button'; exportButton.textContent = 'Veröffentlichungspaket herunterladen';
      const message = document.createElement('p'); message.setAttribute('role', 'status');
      exportButton.onclick = async () => {
        exportButton.disabled = true; message.textContent = 'PDFs werden gebaut und das Paket wird geprüft …';
        try {
          const blob = await api('/api/plugins/lernstand/export', { method: 'POST', body: JSON.stringify({ path: unit.path, loesungen: includeSolutions.checked }), responseType: 'blob', timeout: 1800000 });
          const url = URL.createObjectURL(blob);
          const link = document.createElement('a'); link.href = url; link.download = `${unit.data.lernstand.id}.zip`; link.click();
          setTimeout(() => URL.revokeObjectURL(url), 60000); message.textContent = 'Paket mit Vorschauseite und Katalog erstellt.';
        } catch (error) { message.textContent = error.message; }
        finally { exportButton.disabled = false; }
      };
      container.append(solutionOption, exportButton, message);
    },
  });
}
