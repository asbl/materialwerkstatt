export const unitTypes = { unterrichtsstunde: 'Unterrichtsstunde', klausur: 'Klausur' };
export function unitTypeSelect(value = 'unterrichtsstunde') {
  return `<label>Typ<select name="typ">${Object.entries(unitTypes).map(([key, label]) => `<option value="${key}" ${key === value ? 'selected' : ''}>${label}</option>`).join('')}</select></label>`;
}

// Merge independent edits automatically; competing changes require a choice.
export function mergeUnitData(base, local, remote) {
  const data = {}, conflicts = [];
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  for (const key of new Set([...Object.keys(base), ...Object.keys(local), ...Object.keys(remote)])) {
    if (same(local[key], base[key])) data[key] = remote[key];
    else if (same(remote[key], base[key]) || same(local[key], remote[key])) data[key] = local[key];
    else { data[key] = local[key]; conflicts.push(key); }
  }
  return { data: structuredClone(data), conflicts };
}

export function unitMatchesTags(unit, input) {
  const wanted = input.split(',').map(tag => tag.trim()).filter(Boolean);
  return wanted.every(tag => (unit.data.tags || []).includes(tag));
}

