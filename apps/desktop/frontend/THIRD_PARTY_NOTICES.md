# Mardas Folio desktop third-party notices

The native desktop editor bundles CodeMirror 6 and its transitive Lezer modules for offline use.
CodeMirror, Lezer, and their bundled modules are Copyright (C) 2018-2026 by Marijn
Haverbeke and others, and are distributed under the MIT License.

Build tooling uses esbuild under the MIT License. esbuild is not required at runtime and is
not included in the installed application.

Exact direct and transitive versions are recorded in `apps/desktop/package-lock.json`.
The generated runtime bundle is `frontend/js/vendor/codemirror-editor.bundle.mjs`.

CodeMirror is bundled with one modification. `@codemirror/view` is patched as the bundle is
built, by `apps/desktop/scripts/codemirror-bidi-patch.mjs`, to correct two behaviours on a line
that changes writing direction: the drawing of a selection over it, and where the Home and End
keys place the caret on it. The patch replaces two internal functions and is documented in full
at that path.

## MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
