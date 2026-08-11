# Staged sidecar runtime

This is a build staging directory. Run:

```bash
python scripts/stage_desktop_runtime.py path/to/Mardas-Folio-*-runtime-*
```

The script validates and atomically stages the frozen runtime. Do not commit
Python or Chromium binaries here.

This file is tracked, and `.gitignore` un-ignores it, so that the directory
exists in a fresh checkout. `tauri.conf.json` declares `resources/sidecar/` as a
bundle resource, and the Tauri build script rejects a resource path that does
not exist — so without this file `cargo test` fails before running a single
test, on any machine that has not built the runtime yet. Staging replaces the
whole directory and then puts this file back, which is what keeps a local build
from deleting it.
