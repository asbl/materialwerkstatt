import { assertCompatibility, resetCompatibility } from "./protocol.js";

export async function api(url, options = {}) {
  const { timeout = 15000, signal, responseType = 'json', ...requestOptions } = options;
  const controller = new AbortController();
  const abort = () => controller.abort(signal.reason);
  if (signal?.aborted) abort();
  else signal?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(() => controller.abort(), timeout);
  const headers = options.body == null || options.body instanceof FormData
    ? options.headers || {}
    : { "Content-Type": "application/json", ...(options.headers || {}) };
  try {
    const endpoint = url.split("?")[0];
    let contract;
    // Der Neustart muss auch mit einem inkompatiblen alten Server erreichbar bleiben.
    if (endpoint.startsWith("/api/") && !["/api/server/restart", "/api/desktop-status"].includes(endpoint)) {
      contract = await assertCompatibility();
      if (controller.signal.aborted) throw new DOMException("Abgebrochen", "AbortError");
    }
    const response = await fetch(url, {
      ...requestOptions,
      signal: controller.signal,
      headers: { ...headers,
        ...(contract ? { "X-Material-API-Version": String(contract.apiVersion), "X-Material-Capabilities": contract.capabilities.join(",") } : {}),
        "X-Material-Token": document.querySelector('meta[name="material-token"]')?.content || "" }
    });
    if (!response.ok) {
      if ([403, 426].includes(response.status)) resetCompatibility();
      const error = await response.json().catch(() => null);
      const failure = new Error(error?.error?.message || `Anfrage fehlgeschlagen (${response.status}).`);
      failure.status = response.status;
      failure.issues = error?.issues;
      failure.retryable = response.status >= 500 || response.status === 429;
      throw failure;
    }
    if (responseType === 'blob') return response.blob();
    const data = await response.json();
    if (["/api/document", "/api/document/metadata"].includes(endpoint) && (typeof data.hasSlides !== "boolean" || typeof data.isPresentation !== "boolean")) {
      const error = new Error("Der Material-UI-Server ist veraltet. Bitte im Einstellungsmenü „Server neu starten“ wählen und die Seite neu laden.");
      error.status = 426;
      error.retryable = false;
      throw error;
    }
    return data;
  } catch (error) {
    if (error.name === "AbortError" || error.name === "TimeoutError") {
      const failure = new Error("Zeitüberschreitung. Bei Schreibaktionen ist unklar, ob sie bereits ausgeführt wurden. Bitte den Stand prüfen.");
      failure.retryable = !signal?.aborted;
      throw failure;
    }
    if (error instanceof TypeError) error.retryable = true;
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}
