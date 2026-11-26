// A job outlives individual HTTP requests; each status request retains its own timeout.
export async function waitForJob(api, identifier, { signal, onUpdate = () => {} } = {}) {
  for (;;) {
    signal?.throwIfAborted();
    const record = await api(`/api/jobs/${encodeURIComponent(identifier)}`, { signal });
    onUpdate(record);
    if (!record.running) {
      if (!record.ok) throw new Error(record.message || "Auftrag fehlgeschlagen.");
      return record;
    }
    await new Promise((resolve, reject) => {
      const abort = () => { clearTimeout(timer); reject(signal.reason); };
      const timer = setTimeout(() => { signal?.removeEventListener("abort", abort); resolve(); }, 750);
      signal?.addEventListener("abort", abort, { once: true });
      if (signal?.aborted) abort();
    });
  }
}
