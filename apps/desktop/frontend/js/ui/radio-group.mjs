/** Apply one keyboard and focus contract to custom radio buttons. */
export function bindRadioGroup(group, { buttons, selectedIndex, onSelect }) {
  const documentRef = group.ownerDocument;
  group.setAttribute("role", "radiogroup");
  buttons.forEach((button, index) => {
    button.setAttribute("role", "radio");
    button.setAttribute("aria-checked", String(index === selectedIndex));
    button.tabIndex = index === Math.max(0, selectedIndex) ? 0 : -1;
    button.addEventListener("click", () => onSelect(index));
    button.addEventListener("keydown", (event) => {
      const rtl = documentRef.documentElement.dir === "rtl";
      const offset = event.key === "ArrowDown" ? 1
        : event.key === "ArrowUp" ? -1
        : event.key === "ArrowRight" ? (rtl ? -1 : 1)
        : event.key === "ArrowLeft" ? (rtl ? 1 : -1) : 0;
      if (!offset || event.altKey || event.ctrlKey || event.metaKey) return;
      event.preventDefault();
      onSelect((index + offset + buttons.length) % buttons.length);
    });
  });
}
