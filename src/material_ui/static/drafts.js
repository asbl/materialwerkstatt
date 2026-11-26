const session = crypto.randomUUID();

function key(root, path) {
  return `material-ui:draft:${JSON.stringify([root, path])}`;
}

export function readDrafts(root, path) {
  try {
    const prefix = key(root, path);
    const keys = new Set([prefix, `${prefix}:${session}`]);
    for (let index = 0; index < localStorage.length; index += 1) {
      const candidate = localStorage.key(index);
      if (candidate?.startsWith(`${prefix}:`)) keys.add(candidate);
    }
    const drafts = [];
    for (const identifier of keys) {
      try {
        const draft = JSON.parse(localStorage.getItem(identifier));
        if (draft && typeof draft.text === "string" && typeof draft.revision === "string") {
          drafts.push({ ...draft, id: identifier });
        }
      } catch {
        continue;
      }
    }
    return drafts.sort((first, second) => (second.updated || 0) - (first.updated || 0));
  } catch {
    return [];
  }
}

export function readDraft(root, path) {
  const drafts = readDrafts(root, path);
  return drafts.find(draft => draft.id === `${key(root, path)}:${session}`) || drafts[0] || null;
}

export function writeDraft(root, path, text, revision) {
  try {
    localStorage.setItem(`${key(root, path)}:${session}`, JSON.stringify({ text, revision, updated: Date.now() }));
    return true;
  } catch {
    return false;
  }
}

export function removeDraft(root, path, text, identifier = `${key(root, path)}:${session}`) {
  try {
    if (identifier !== key(root, path) && !identifier.startsWith(`${key(root, path)}:`)) return;
    if (JSON.parse(localStorage.getItem(identifier))?.text === text) localStorage.removeItem(identifier);
  } catch {
    return;
  }
}
