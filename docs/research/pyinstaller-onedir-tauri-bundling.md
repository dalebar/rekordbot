# Research: Bundling PyInstaller `--onedir` Output in Tauri v2

**Date:** 2026-03-09
**Context:** Phase 6b — `.dmg` packaging. The sidecar binary builds and runs correctly in dev mode, but the `.app` bundle is missing PyInstaller's `_internal/` directory at runtime.

---

## The Problem

PyInstaller `--onedir` produces two things:

```
dist/rekordbot-server/
├── rekordbot-server          ← the executable
└── _internal/                ← all Python deps (~200MB)
    ├── libpython3.13.dylib
    ├── numpy/
    ├── sqlalchemy/
    └── ... (hundreds of files)
```

The executable **must** find `_internal/` in the same directory as itself at runtime. This is hardcoded in PyInstaller's compiled bootloader — it sets `sys._MEIPASS` to `<executable_dir>/_internal/` before any Python code runs. There is no environment variable or runtime override.

Tauri's `externalBin` bundles the sidecar executable into `Contents/MacOS/`, but **only the executable** — not the `_internal/` directory. The current build script copies both into `src-tauri/binaries/`, but Tauri ignores the directory.

Result: the `.app` launches, spawns the sidecar, and the sidecar immediately crashes because it can't find `_internal/`.

### Why not `--onefile`?

This was evaluated in Session 1 (see `docs/research/tauri-python-backend-research.md`) and rejected for three reasons:

1. **Zombie process risk** — `--onefile` extracts to a temp directory on every launch. If the sidecar crashes or is killed (normal in sidecar lifecycle), temp directories accumulate.
2. **Code signing** — Phase 6f needs to sign all binaries individually. `--onefile` embeds everything in a single binary that extracts at runtime, which is significantly harder to sign and notarise.
3. **Startup time** — Extraction adds real seconds to every cold start for a bundle this size (~200MB of Python deps).

These reasons still hold. We need a solution that keeps `--onedir`.

---

## How PyInstaller Resolves `_internal/`

- The bootloader (compiled C code, not Python) resolves `_internal/` **relative to the executable's location** at startup
- `sys._MEIPASS` is set to the absolute path of `_internal/` — this cannot be overridden at runtime
- The directory name `_internal` can be changed at build time via `--contents-directory=<name>`, but the "relative to executable" resolution cannot
- `_internal/` **can be a symlink** — PyInstaller follows symlinks correctly (confirmed in PyInstaller issue #9263)

**Bottom line:** wherever the sidecar executable lives at runtime, `_internal/` must be a sibling in the same directory (or a symlink to one).

---

## Tauri v2 macOS Bundle Structure

```
rekordbot.app/
└── Contents/
    ├── MacOS/
    │   ├── rekordbot                              ← Tauri main executable
    │   └── rekordbot-server-aarch64-apple-darwin   ← sidecar (from externalBin)
    │   └── _internal/                              ← MISSING — this is what we need
    ├── Resources/
    │   ├── icon.icns
    │   └── resources/
    │       └── ffmpeg                              ← from bundle.resources
    └── Info.plist
```

Tauri v2 provides three mechanisms for placing files in the bundle:

| Mechanism | Destination in `.app` | Supports directories? |
|---|---|---|
| `bundle.externalBin` | `Contents/MacOS/` | No — single executable only |
| `bundle.resources` | `Contents/Resources/resources/` | Yes — glob patterns |
| `bundle.macOS.files` | `Contents/<you specify>` | Unknown — docs only show single files |

---

## Options

### Option 1: `bundle.macOS.files` (if it supports directories)

**Config change only — add to `tauri.conf.json`:**

```json
"macOS": {
  "files": {
    "MacOS/_internal": "binaries/_internal"
  },
  "dmg": { ... }
}
```

**How it works:** Tauri copies `src-tauri/binaries/_internal/` into `Contents/MacOS/_internal/` during bundling. The sidecar finds it at runtime because it's a sibling.

**Pros:**
- Simplest solution — one config line, no code changes
- No runtime overhead
- `_internal/` is in the correct location for code signing (Contents/MacOS/)

**Cons:**
- Tauri docs only show single-file examples for `bundle.macOS.files` — directory support is undocumented
- If it doesn't work, we find out at build time (low-risk to test)

**Risk:** Low. If it doesn't support directories, the build will fail or produce an incomplete bundle. Easy to detect, no data loss.

### Option 2: Resources + runtime symlink from `main.rs`

**Bundle `_internal/` as a resource, then symlink before spawning the sidecar:**

```json
"resources": [
  "resources/*",
  "binaries/_internal/**/*"
]
```

In `main.rs`, before spawning the sidecar:

```rust
// Create symlink: Contents/MacOS/_internal -> Contents/Resources/resources/_internal
let macos_dir = app.path().resource_dir().parent().join("MacOS");
let internal_link = macos_dir.join("_internal");
let resource_internal = app.path().resource_dir().join("_internal");
std::os::unix::fs::symlink(&resource_internal, &internal_link).ok();
```

**Pros:**
- `bundle.resources` definitely supports directories (glob patterns)
- Symlink means no file duplication

**Cons:**
- Runtime symlink creation — needs to happen before sidecar spawn
- The `.app` bundle's `Contents/MacOS/` is read-only after installation... actually it's writable by the owning user, but creating files there at runtime is unusual
- Symlink may not survive code signing (Phase 6f) — codesign validates the bundle structure
- More complex than Option 1

**Risk:** Medium. Symlinks in signed bundles can cause validation failures. Would need to be re-evaluated in Phase 6f.

### Option 3: Post-build injection (split Tauri build)

**Build the `.app` first, inject `_internal/`, then create the `.dmg`:**

```makefile
build-dmg:
	@echo "Building Python sidecar..."
	./scripts/build-backend.sh
	@echo "Building Tauri app..."
	cd frontend && npx tauri build --bundles app
	@echo "Injecting PyInstaller dependencies..."
	cp -r frontend/src-tauri/binaries/_internal \
	  frontend/src-tauri/target/release/bundle/macos/rekordbot.app/Contents/MacOS/_internal
	@echo "Creating DMG..."
	# Use hdiutil or create-dmg to package the .app
	hdiutil create -volname rekordbot -srcfolder \
	  frontend/src-tauri/target/release/bundle/macos/rekordbot.app \
	  -ov -format UDZO \
	  frontend/src-tauri/target/release/bundle/dmg/rekordbot_0.1.0_aarch64.dmg
	@echo "DMG ready"
```

**Pros:**
- Guaranteed to work — we control the full pipeline
- `_internal/` ends up exactly where it needs to be
- No Tauri feature dependencies

**Cons:**
- Loses Tauri's `.dmg` layout (app icon positioning, Applications shortcut) — we'd need to replicate that with `create-dmg` or a custom AppleScript
- More complex build script
- Fragile — depends on knowing Tauri's output paths
- The `--bundles app` flag may not exist (needs verification)

**Risk:** Medium. Build complexity increases. The `.dmg` creation would need its own tooling.

### Option 4: Modify `build-backend.sh` to restructure output

**Instead of copying `_internal/` into `src-tauri/binaries/`, flatten it into `resources/`:**

The sidecar stays as a single executable in `externalBin`. The `_internal/` directory gets bundled as a Tauri resource. At runtime, the sidecar can't find `_internal/` next to itself... unless we use the `--contents-directory` flag to tell PyInstaller to look elsewhere.

**Problem:** PyInstaller's `--contents-directory` changes the *name* of the directory, not its *location*. It's still resolved relative to the executable. This option doesn't work.

### Option 5: Pre-spawn copy in `main.rs`

**Bundle `_internal/` as a resource. Before spawning the sidecar, copy (not symlink) the entire directory to `Contents/MacOS/_internal/`:**

```rust
// On first launch, copy _internal from Resources to MacOS
let resource_internal = app.path().resource_dir().join("_internal");
let macos_internal = exe_dir.join("_internal");
if !macos_internal.exists() && resource_internal.exists() {
    fs_extra::dir::copy(&resource_internal, &exe_dir, &options).unwrap();
}
```

**Pros:**
- Resources definitely support directories
- Copy only happens once (persists across launches)

**Cons:**
- Doubles the storage for `_internal/` (~200MB in resources + ~200MB copied to MacOS)
- First launch is slow (copying ~200MB)
- Writing into `Contents/MacOS/` of a signed app would invalidate the signature
- Requires `fs_extra` or similar crate dependency

**Risk:** High. Code signing incompatible. Storage waste. Ruled out.

---

## Recommendation

**Try Option 1 first.** It's a one-line config change with zero risk — if `bundle.macOS.files` doesn't support directories, the build fails immediately and we know. If it works, it's the cleanest solution by far.

**If Option 1 fails, go with Option 3** (post-build injection). It's more complex but gives us full control. The `.dmg` layout can be replicated with the `create-dmg` npm package or a simple `hdiutil` command.

Options 2 and 5 have code signing concerns that would create problems in Phase 6f. Option 4 doesn't work at all.

---

## Sources

- [Tauri v2 macOS Application Bundle](https://v2.tauri.app/distribute/macos-application-bundle/)
- [Tauri v2 Configuration Reference](https://v2.tauri.app/reference/config/)
- [Tauri v2 Embedding External Binaries](https://v2.tauri.app/develop/sidecar/)
- [Tauri v2 Embedding Additional Files / Resources](https://v2.tauri.app/develop/resources/)
- [PyInstaller Runtime Information — sys._MEIPASS](https://pyinstaller.org/en/stable/runtime-information.html)
- [PyInstaller --contents-directory option](https://pyinstaller.org/en/stable/usage.html)
- [PyInstaller Issue #9263 — Symlinks for _internal](https://github.com/pyinstaller/pyinstaller/issues/9263)
- [Tauri Issue #3290 — Copy content to Contents/Library](https://github.com/tauri-apps/tauri/issues/3290)
- rekordbot `docs/research/tauri-python-backend-research.md` (Session 1 sidecar research)
