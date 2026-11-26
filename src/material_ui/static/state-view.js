// Declare the fields a feature may access. Features cannot add undeclared fields;
// callbacks belong in controller arguments, never state.
export function stateView(state, keys) {
  const view = {};
  for (const key of keys) {
    Object.defineProperty(view, key, {
      enumerable: true,
      get: () => state[key],
      set: value => { state[key] = value; }
    });
  }
  return Object.seal(view);
}
