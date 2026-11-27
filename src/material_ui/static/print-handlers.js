// Druckwege für „PDF drucken“: Plugins können den Druck des aktuellen PDFs übernehmen,
// etwa um Exemplare und Duplex vorzugeben, die der Browser-Druckdialog nicht kennt.
// Ein Handler erhält `{ path, pdf, url, browserPrint }` und liefert `false`, wenn er den
// Druck nicht übernimmt; dann öffnet der Kern wie bisher den Druckdialog des Browsers.
// Der zuletzt registrierte Handler gewinnt.
export function createPrintHandlerRegistry() {
  const handlers = [];
  return {
    register(handler) {
      if (!handler || typeof handler.print !== "function") throw new Error("Druck-Handler braucht print().");
      const entry = { ...handler };
      handlers.push(entry);
      return () => {
        const index = handlers.indexOf(entry);
        if (index >= 0) handlers.splice(index, 1);
      };
    },
    active() {
      return handlers.at(-1) || null;
    },
  };
}
