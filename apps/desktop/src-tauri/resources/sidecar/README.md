# Staged sidecar runtime

This is a build staging directory. Run:

```bash
python scripts/stage_desktop_runtime.py path/to/Mardas-MD2PDF-*-runtime-*
```

The script validates and atomically stages the frozen runtime. Do not commit Python or Chromium binaries here.
