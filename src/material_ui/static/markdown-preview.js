// Live preview uses the current editor buffer, independently of autosave and PDF builds.
export function createMarkdownPreview({ state, api, getText, canRender }) {
  const host = document.getElementById('markdownPreviewHost');
  let frame;
  const resolvers = [];
  const message = document.getElementById('markdownPreviewStatus');
  let timer, generation = 0, request;
  function schedule() {
    clearTimeout(timer);
    request?.abort();
    const version = ++generation;
    const active = !state.course.kursMode && /\.md$/i.test(state.qmdPath) && !canRender();
    host.hidden = !active;
    message.hidden = !active;
    document.body.classList.toggle('markdown-document', active);
    if (!active) { host.replaceChildren(); frame = null; return; }
    if (!frame) {
      frame = document.createElement('iframe'); frame.id = 'markdownPreview';
      frame.title = 'Markdown-Vorschau'; frame.setAttribute('sandbox', '');
      host.append(frame);
    }
    message.textContent = 'Markdown-Vorschau wird aktualisiert …';
    const path = state.qmdPath;
    timer = setTimeout(async () => {
      const controller = new AbortController();
      request = controller;
      try {
        const preview = resolvers.map(resolve => resolve(path)).find(Boolean)
          || { url: '/api/document/preview', path };
        const result = await api(preview.url, {
          method: 'POST', body: JSON.stringify({path: preview.path, text: getText()}), signal: controller.signal
        });
        if (version !== generation) return;
        frame.srcdoc = result.html;
        message.textContent = 'Markdown-Vorschau · aktueller Text';
      } catch (error) {
        if (version === generation) message.textContent = `Vorschau fehlgeschlagen: ${error.message}`;
      }
    }, 250);
  }
  document.addEventListener('material-document-opened', schedule);
  document.addEventListener('material-document-saved', schedule);
  return { schedule, registerResolver: resolve => resolvers.push(resolve) };
}
