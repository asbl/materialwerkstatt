// Owns the fulltext search state of the picker (results, sources, load token, timer),
// independently of the global app state. Only the picker controller reads and writes it.
export function createFulltextState() {
  return {
    results: [],
    sources: [],
    key: null,
    load: 0,
    timer: null,
  };
}
