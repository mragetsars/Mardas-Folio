import { StateEffect, StateField } from "@codemirror/state";
import { Decoration, EditorView } from "@codemirror/view";

export const searchMatchesEffect = StateEffect.define();

/** Host search owns literal/Persian folding and offsets; paint those same matches. */
export const searchHighlights = StateField.define({
  create: () => Decoration.none,
  update(value, transaction) {
    value = value.map(transaction.changes);
    for (const effect of transaction.effects) {
      if (!effect.is(searchMatchesEffect)) continue;
      const { matches = [], index = -1 } = effect.value;
      value = Decoration.set(
        matches.slice(0, 10_000).flatMap((match, at) => {
          const from = Number(match.start),
            to = Number(match.end);
          if (
            !Number.isInteger(from) ||
            !Number.isInteger(to) ||
            from < 0 ||
            to <= from ||
            to > transaction.state.doc.length
          )
            return [];
          return [
            Decoration.mark({
              class: at === index ? "cm-findMatch cm-findMatch-current" : "cm-findMatch",
            }).range(from, to),
          ];
        }),
        true,
      );
    }
    return value;
  },
  provide: (field) => EditorView.decorations.from(field),
});
