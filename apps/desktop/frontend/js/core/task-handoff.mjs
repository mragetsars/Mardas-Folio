const DEFAULT_HANDOFF_TIMEOUT_MS = 5_000;

export function waitForTaskSettlement(
  completion,
  {
    timeoutMs = DEFAULT_HANDOFF_TIMEOUT_MS,
    setTimer = globalThis.setTimeout,
    clearTimer = globalThis.clearTimeout,
  } = {},
) {
  if (!completion) return Promise.resolve(true);
  const numericTimeout = Number(timeoutMs);
  const boundedTimeout = Number.isFinite(numericTimeout)
    ? Math.max(0, Math.trunc(numericTimeout))
    : DEFAULT_HANDOFF_TIMEOUT_MS;

  return new Promise((resolve) => {
    let finished = false;
    let timer = null;
    const finish = (settled) => {
      if (finished) return;
      finished = true;
      if (timer !== null) clearTimer(timer);
      resolve(settled);
    };
    timer = setTimer(() => finish(false), boundedTimeout);
    Promise.resolve(completion).then(
      () => finish(true),
      () => finish(true),
    );
  });
}

export function beginCancellationHandoff({ completion = null, cancel = null, ...options } = {}) {
  if (typeof cancel === "function") {
    try {
      Promise.resolve(cancel()).catch(() => {
        // Cancellation is best-effort; task settlement or the bounded timeout
        // still releases the next project transition.
      });
    } catch {
      // A synchronous transport failure follows the same bounded handoff path.
    }
  }
  return waitForTaskSettlement(completion, options);
}
