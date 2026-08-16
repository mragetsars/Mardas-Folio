import { createHash } from "node:crypto";
import { mkdir, readFile, rename, unlink, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

import { codeMirrorBidiSelectionPatch } from "./codemirror-bidi-selection-patch.mjs";

const desktopRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const entryPoint = resolve(desktopRoot, "editor-src/codemirror-editor.mjs");
const outputPath = resolve(
  desktopRoot,
  "frontend/js/vendor/codemirror-editor.bundle.mjs",
);
const checkOnly = process.argv.includes("--check");

const result = await build({
  absWorkingDir: desktopRoot,
  banner: {
    js: "/* Bundled locally for Mardas Folio; see THIRD_PARTY_NOTICES.md. */",
  },
  bundle: true,
  charset: "utf8",
  entryPoints: [entryPoint],
  format: "esm",
  legalComments: "eof",
  minify: true,
  platform: "browser",
  plugins: [codeMirrorBidiSelectionPatch()],
  sourcemap: false,
  target: ["es2020"],
  treeShaking: true,
  write: false,
});

if (result.outputFiles.length !== 1) {
  throw new Error(`Expected one editor bundle, received ${result.outputFiles.length}.`);
}

const bundle = result.outputFiles[0].contents;
const digest = createHash("sha256").update(bundle).digest("hex");

if (checkOnly) {
  let committed;
  try {
    committed = await readFile(outputPath);
  } catch (error) {
    if (error?.code === "ENOENT") {
      throw new Error("The committed CodeMirror bundle is missing.");
    }
    throw error;
  }
  if (!committed.equals(bundle)) {
    throw new Error(
      "The committed CodeMirror bundle is stale. Run `npm run build:editor` in apps/desktop.",
    );
  }
  console.log(`CodeMirror bundle verified: sha256:${digest}`);
} else {
  await mkdir(dirname(outputPath), { recursive: true });
  const temporary = `${outputPath}.tmp-${process.pid}`;
  try {
    await writeFile(temporary, bundle, { mode: 0o644 });
    await rename(temporary, outputPath);
  } finally {
    await unlink(temporary).catch((error) => {
      if (error?.code !== "ENOENT") throw error;
    });
  }
  console.log(`CodeMirror bundle written: sha256:${digest}`);
}
