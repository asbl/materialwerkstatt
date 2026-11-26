// Pfad-Resolver: Plugins lösen unbekannte Pfade auf (z. B. Kurs-MDX → Kurs-Eintrag),
// bevor der Kern sie als QMD öffnet. Reihenfolge: Registrierung.

export function createPathResolverRegistry() {
  const resolvers = [];

  function register(resolver) {
    if (typeof resolver !== "function") return () => {};
    resolvers.push(resolver);
    return () => {
      const index = resolvers.indexOf(resolver);
      if (index !== -1) resolvers.splice(index, 1);
    };
  }

  function resolve(path) {
    for (const resolver of resolvers) {
      const entry = resolver(path);
      if (entry) return entry;
    }
    return undefined;
  }

  return { register, resolve, count: () => resolvers.length };
}
