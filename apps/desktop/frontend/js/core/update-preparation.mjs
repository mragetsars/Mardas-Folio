/** Save real files before an installer can terminate the process. */
export async function saveDocumentsBeforeUpdate({ getDocuments, isDirty, confirm, save }) {
  const pending = getDocuments().filter(isDirty);
  if (pending.length && !await confirm()) return false;
  for (const model of pending) {
    if (!getDocuments().includes(model) || !isDirty(model)) continue;
    // The save coordinator also waits for an earlier save of this document.
    // A cancelled picker, conflict or disk failure cancels installation.
    if (!await save(model) || isDirty(model)) return false;
  }
  return !getDocuments().some(isDirty);
}
