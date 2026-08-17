/**
 * Reading Persian the way it is typed rather than the way it is encoded.
 *
 * The same Persian word reaches the application in several encodings that are
 * indistinguishable on screen, and every one of them is what some real
 * keyboard, older Windows install, or pasted web page produces. Comparing the
 * raw code points makes the interface answer "there is no such thing" to a word
 * the user can see in front of them.
 *
 * Two rules, kept apart because they are not interchangeable:
 *
 * - `foldPersianLetters` maps each letter to one character, so offsets survive
 *   and a match can still be turned into a selection range. Document search
 *   depends on that.
 * - `foldForFilter` is for filtering a list, where nothing downstream needs an
 *   offset, so it can also drop the zero-width joiners that Persian text is
 *   full of and case-fold the Latin mixed in with it.
 */

/**
 * One Persian letter, typed two ways.
 *
 * A Persian keyboard produces ی U+06CC and ک U+06A9; an Arabic layout, older
 * Windows keyboards, and most text pasted from the web produce ي U+064A and
 * ك U+0643.
 *
 * Each mapping is one character to one character, so folding leaves every
 * offset where it was and the match positions stay valid selection ranges.
 * Letters that merely look similar are left alone: آ and ا are different
 * letters in Persian, and Persian and Latin digits mean different things.
 */
const PERSIAN_LETTER_FOLD = /[يىك]/g;
const PERSIAN_FOLDED = { "ي": "ی", "ى": "ی", "ك": "ک" };

export function foldPersianLetters(value) {
  return String(value ?? "").replace(PERSIAN_LETTER_FOLD, (ch) => PERSIAN_FOLDED[ch]);
}

/**
 * Joiners that separate Persian words without printing anything.
 *
 * `پیش‌نمایش` carries a zero-width non-joiner between its two halves; a reader
 * looking at the label cannot tell whether to type that, a space, or nothing,
 * and all three are the same word. Removing them from both sides of a
 * comparison makes every spelling match, which is only safe where the result is
 * a yes/no rather than a position in a document.
 */
const ZERO_WIDTH = /[\u200b-\u200f\u2060\ufeff]/g;

/** Normalize a value for matching against a list of interface labels. */
export function foldForFilter(value) {
  return foldPersianLetters(value)
    .replace(ZERO_WIDTH, "")
    .trim()
    .toLocaleLowerCase();
}
