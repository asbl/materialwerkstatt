let contractPromise = null;
let compatibilityPromise = null;
let checkedAt = 0;
const COMPATIBILITY_TTL = 30000;

export function resetCompatibility() {
  compatibilityPromise = null;
  checkedAt = 0;
}

function incompatible() {
  const error = new Error("Material-UI und Server sind nicht kompatibel. Bitte den Server im Einstellungsmenü neu starten und die Seite neu laden.");
  error.status = 426;
  error.retryable = false;
  return error;
}

export function validateProtocol(contract, server) {
  if (!contract || !Number.isInteger(contract.apiVersion) || !Array.isArray(contract.capabilities)
    || !server || server.apiVersion !== contract.apiVersion || !Array.isArray(server.capabilities)
    || contract.capabilities.some(capability => !server.capabilities.includes(capability))) throw incompatible();
}

export async function assertCompatibility(refresh = false) {
  const assetVersion = new URL(import.meta.url).searchParams.get("v");
  const contractUrl = "/static/api-contract.json" + (assetVersion ? `?v=${encodeURIComponent(assetVersion)}` : "");
  contractPromise ||= fetch(contractUrl, { cache: "no-store", signal: AbortSignal.timeout(5000) }).then(async response => {
    if (!response.ok) throw incompatible();
    return response.json();
  }).catch(error => { contractPromise = null; throw error; });
  if (refresh || !compatibilityPromise || Date.now() - checkedAt >= COMPATIBILITY_TTL) {
    checkedAt = Date.now(); // Concurrent callers share the in-flight validation too.
    compatibilityPromise = (async () => {
      const contract = await contractPromise;
      const response = await fetch("/api/protocol", { cache: "no-store", signal: AbortSignal.timeout(5000) });
      if (!response.ok) {
        if ([404, 426].includes(response.status)) throw incompatible();
        const error = new Error("Server-Kompatibilität konnte nicht geprüft werden. Bitte erneut versuchen.");
        error.status = response.status;
        error.retryable = response.status >= 500 || response.status === 429;
        throw error;
      }
      validateProtocol(contract, await response.json());
      checkedAt = Date.now();
      return contract;
    })();
  }
  try {
    return await compatibilityPromise;
  } catch (error) {
    compatibilityPromise = null;
    if (error.status === 426) throw error;
    if (error instanceof SyntaxError) throw incompatible();
    if (error instanceof TypeError) error.retryable = true;
    throw error;
  }
}
