/**
 * Run one instance of a task at a time, keeping only the newest request.
 *
 * The publishing engine takes a single job and answers the next with
 * SERVER_BUSY. Preview work is speculative and cannot be interrupted — laying
 * out the page is Markdown work that never sees the cancellation flag — so on
 * a long document it holds the engine for seconds. Anything sent during that
 * window fails, and the failure lands on screen as though the document were at
 * fault.
 *
 * Only the newest request carries any information, so a call that arrives while
 * the task is running is remembered rather than sent, and runs once when the
 * engine is free. Several calls in a row therefore cost one extra run, not one
 * each.
 */
export function createSingleFlight(task) {
  let running = null;
  let queued = false;

  async function run() {
    if (running) {
      queued = true;
      return;
    }
    let started;
    try {
      started = Promise.resolve(task());
    } catch (error) {
      // A task that throws synchronously must not wedge the runner shut.
      return Promise.reject(error);
    }
    running = started;
    try {
      await started;
    } finally {
      running = null;
      if (queued) {
        queued = false;
        void run();
      }
    }
  }

  return {
    run,

    /**
     * Wait for the engine to come free, and drop any queued rerun.
     *
     * Used before a job the user actually asked for: the speculative work
     * cannot be stopped, but the real job can wait for it rather than being
     * refused, and must not be followed by a preview that was queued behind it.
     */
    async drain() {
      queued = false;
      try {
        await running;
      } catch {
        // A failed task releases the engine just as well as a successful one.
      }
      queued = false;
    },

    get isRunning() {
      return running !== null;
    },

    get hasQueuedRun() {
      return queued;
    },
  };
}
