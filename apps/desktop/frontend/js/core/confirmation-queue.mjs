/** Each destructive decision is presented and answered independently. */
export function createConfirmationQueue(present) {
  if (typeof present !== "function") throw new TypeError("present must be a function");
  let tail = Promise.resolve();
  return (details) => {
    const answer = tail.then(() => present(details));
    // A failed presenter must not strand unrelated decisions behind it.
    tail = answer.catch(() => false);
    return answer;
  };
}
