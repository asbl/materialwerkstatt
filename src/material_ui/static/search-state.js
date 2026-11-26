// Owns query state independently of document labels displayed in the search box.
export function createSearchState({ elements, getContext }) {
  const queries = { global: "", tagTree: "" };
  const context = () => getContext() === "tagTree" ? "tagTree" : "global";
  function setQuery(value, scope = context()) {
    queries[scope] = String(value);
    if (scope === "tagTree") elements.tagSearch.value = queries[scope];
    if (scope === context()) elements.documentSearch.value = queries[scope];
  }
  return Object.freeze({
    query: (scope = context()) => queries[scope],
    setQuery,
    activate(scope) { elements.documentSearch.value = queries[scope]; },
    displayDocument(label) {
      if (context() === "global") {
        queries.global = "";
        elements.documentSearch.value = label;
      }
    },
    closeDocument() {
      if (context() === "global") setQuery("", "global");
    }
  });
}
