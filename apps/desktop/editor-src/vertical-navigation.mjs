import { EditorSelection, Transaction } from "@codemirror/state";

/** Keep real blank rows reachable when their prose spacing is shorter.
 * CodeMirror's geometric movement can step across a 12px paragraph separator
 * when the surrounding font is 20px. Wrapped text still follows the normal
 * visual movement; only an actually skipped adjacent empty line is handled.
 */
export function moveAcrossCompressedSpacer(view, forward, extend = false) {
  const { selection, doc } = view.state;
  if (selection.ranges.length !== 1 || (!extend && !selection.main.empty)) return false;
  const current = selection.main;
  const line = doc.lineAt(current.head);
  const adjacentNumber = line.number + (forward ? 1 : -1);
  if (adjacentNumber < 1 || adjacentNumber > doc.lines) return false;
  const adjacent = doc.line(adjacentNumber);
  if (adjacent.text.trim()) return false;
  const visual = view.moveVertically(current, forward);
  const destination = doc.lineAt(visual.head).number;
  if (forward ? destination <= adjacentNumber : destination >= adjacentNumber) return false;
  view.dispatch({
    selection: extend ? EditorSelection.range(current.anchor, adjacent.from) : EditorSelection.cursor(adjacent.from),
    scrollIntoView: true,
    annotations: Transaction.userEvent.of("select.keyboard"),
  });
  return true;
}
