export function createSaveCoordinator({ isDirty }) {
  if (typeof isDirty !== "function") throw new TypeError("isDirty must be a function");
  const pending = new Map();

  async function save(document, operation, { alwaysRun = false } = {}) {
    if (!document?.id || typeof operation !== "function") return false;
    const previous = pending.get(document.id);
    const current = (async () => {
      if (previous) {
        const completed = await previous;
        if (!completed) return false;
        if (!alwaysRun && !isDirty(document)) return true;
      }
      return operation(document);
    })();
    pending.set(document.id, current);
    try {
      return await current;
    } finally {
      if (pending.get(document.id) === current) pending.delete(document.id);
    }
  }

  return {
    save,
    isSaving(documentId) {
      return pending.has(documentId);
    },
  };
}
