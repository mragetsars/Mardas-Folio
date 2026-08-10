/**
 * Typewriter scrolling.
 *
 * Writing at the bottom edge of a window is uncomfortable: there is nothing
 * below the line being written, so the eye has no context and the text keeps
 * creeping downward. Typewriter mode keeps the caret's line at a fixed height
 * in the viewport, so the page moves under the words instead of the words
 * moving down the page.
 *
 * It is off by default. Scroll position is something people build a physical
 * habit around, and taking that over uninvited is disorienting.
 */
import { EditorView, ViewPlugin } from "@codemirror/view";

/** Where the caret line sits, as a fraction of the visible height. */
const ANCHOR = 0.42;

const typewriterPlugin = ViewPlugin.fromClass(
  class {
    constructor(view) {
      this.centre(view);
    }

    update(update) {
      if (!update.selectionSet && !update.docChanged) return;
      // Scrolling from inside an update would fight the measure phase, so the
      // work is queued for after it.
      update.view.requestMeasure({
        read: () => null,
        write: () => this.centre(update.view),
      });
    }

    centre(view) {
      const head = view.state.selection.main.head;
      const block = view.lineBlockAt(head);
      const target = block.top - view.scrollDOM.clientHeight * ANCHOR + block.height / 2;
      const maximum = view.scrollDOM.scrollHeight - view.scrollDOM.clientHeight;
      const next = Math.max(0, Math.min(target, Math.max(0, maximum)));
      if (Math.abs(view.scrollDOM.scrollTop - next) < 2) return;
      view.scrollDOM.scrollTop = next;
    }
  },
);

/**
 * Extra bottom padding so the last line can reach the anchor.
 *
 * Without it the final paragraph of a document cannot be scrolled up to the
 * writing line, and typewriter mode quietly stops working exactly where a
 * writer spends most of their time.
 */
const typewriterPadding = EditorView.theme({
  "&.cm-editor .cm-content": { paddingBottom: "58vh" },
});

export function typewriterExtension(enabled) {
  return enabled ? [typewriterPlugin, typewriterPadding] : [];
}
