export function bookTaskBlocked(state) {
  return Boolean(
    state?.activeBookRequestId
    || state?.activeBookCompletion
    || state?.bookCancellationHandoff,
  );
}

export function claimBookTask(state, startTask) {
  if (!state || typeof startTask !== "function" || bookTaskBlocked(state)) return null;
  const task = startTask();
  if (!task || !("promise" in task)) {
    throw new TypeError("A book task must expose a promise.");
  }
  const promise = Promise.resolve(task.promise);
  const completion = promise.then(
    () => undefined,
    () => undefined,
  );
  state.activeBookRequestId = task.requestId || null;
  state.activeBookCompletion = completion;
  return { requestId: task.requestId || null, promise, completion };
}
