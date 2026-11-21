export function enableDialogBackdrop(dialog, canClose = () => true) {
  let beganOutside = false,
    endedOutside = false,
    pointerId = null;
  function outside(e) {
    const r = dialog.getBoundingClientRect();
    return (
      e.target === dialog &&
      (e.clientX < r.left || e.clientX >= r.right || e.clientY < r.top || e.clientY >= r.bottom)
    );
  }
  dialog.addEventListener("pointerdown", (e) => {
    pointerId = e.pointerId;
    beganOutside = e.button === 0 && outside(e);
    endedOutside = false;
  });
  dialog.addEventListener("pointerup", (e) => {
    endedOutside = e.pointerId === pointerId && outside(e);
  });
  dialog.addEventListener("pointercancel", () => {
    beganOutside = endedOutside = false;
  });
  dialog.addEventListener("click", (e) => {
    const dismiss = beganOutside && endedOutside && outside(e);
    beganOutside = endedOutside = false;
    if (dismiss && canClose()) {
      e.preventDefault();
      dialog.close();
    }
  });
}
