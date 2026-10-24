/** The sidecar has one work slot. Keep file operations and previews in order. */
export function createEngineQueue() {
  let active = null;
  const waiting = [];

  function advance() {
    if (active || !waiting.length) return;
    const interactive = waiting.findIndex((job) => !job.speculative);
    const job = waiting.splice(interactive < 0 ? 0 : interactive, 1)[0];
    active = job;
    let result;
    try { result = job.run(); }
    catch (error) { result = Promise.reject(error); }
    Promise.resolve(result).then(job.resolve, job.reject).finally(() => {
      active = null;
      advance();
    });
  }

  return {
    run(id, run, { speculative = false } = {}) {
      return new Promise((resolve, reject) => {
        waiting.push({ id, run, speculative, resolve, reject });
        advance();
      });
    },
    cancel(id) {
      const index = waiting.findIndex((job) => job.id === id);
      if (index < 0) return false;
      const [job] = waiting.splice(index, 1);
      job.reject(JSON.stringify({
        message: "The operation was cancelled.",
        data: { application_code: "MARDAS-JOB-CANCELLED" },
      }));
      return true;
    },
  };
}
