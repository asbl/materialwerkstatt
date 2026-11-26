// Build capability and the visible teaching action are separate decisions.
export function updatePresentationActions(button, data) {
  const note = data.capabilities?.render === false;
  document.body.classList.toggle("note-document", note);
  button.hidden = !data.isPresentation || !data.hasSlides;
  document.dispatchEvent(new CustomEvent("material-presentation-actions", {
    detail: { presentation: Boolean(data.isPresentation), present: data.capabilities?.present !== false }
  }));
}
