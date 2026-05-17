# rekordbot — Tauri + Python Backend Lifecycle Research

*Research document for Chat B. Produced for decision-making in the main development chat.*

---

## 1. Sidecar Architecture

### How Tauri's Sidecar Feature Works

Tauri's sidecar feature allows you to bundle external binaries alongside your app. The binary is declared in `tauri.conf.json` under `bundle.externalBin`, and Tauri handles including it in the final distributable package.

**Naming convention:** Tauri requires sidecar binaries to follow a strict naming pattern. The binary must be suffixed with the platform's target triple. For example, if your config says `"externalBin": ["binaries/rekordbot-server"]`, Tauri expects:

- `src-tauri/binaries/rekordbot-server-aarch64-apple-darwin` (macOS Apple Silicon)
- `src-tauri/binaries/rekordbot-server-x86_64-apple-darwin` (macOS Intel)
- `src-tauri/binaries/rekordbot-server-x86_64-pc-windows-msvc.exe` (Windows)
- `src-tauri/binaries/rekordbot-server-x86_64-unknown-linux-gnu` (Linux)

You can get your current platform's triple by running `rustc --print host-tuple`.

**Path resolution:** Paths in `externalBin` are relative to the `src-tauri/` directory. So `"binaries/rekordbot-server"` resolves to `src-tauri/binaries/rekordbot-server-{target-triple}`.

**Permissions (Tauri v2):** The shell plugin must be installed and configured. You need to grant sidecar execution permission in `src-tauri/capabilities/default.json`:

```json
{
  "identifier": "shell:allow-spawn",
  "allow": [
    {
      "name": "binaries/rekordbot-server",
      "sidecar": true,
      "args": true
    }
  ]
}
```

Setting `"args": true` allows any arguments. For production you could lock this down to specific argument patterns using regex validators.

### Process Lifecycle

**Spawning:** The sidecar is spawned either from Rust (`app.shell().sidecar("rekordbot-server")`) or from JavaScript (`Command.sidecar("binaries/rekordbot-server")`). Use `.spawn()` for long-running processes (like our FastAPI server) rather than `.execute()` which blocks until the process exits.

**Shutdown — the critical detail:** Tauri does NOT automatically kill sidecar processes when the app closes. The official docs are explicit: "you are in charge of killing the child process when your app closes; otherwise, you pollute the user's machine with orphan processes." Since Tauri v1.0.3, Tauri emits a `RunEvent::Exit` event before killing child processes, allowing graceful shutdown.

The recommended Rust-side pattern is:

```rust
#[derive(Default)]
struct Backend(Option<CommandChild>);

fn main() {
    let mut backend = Backend::default();
    tauri::Builder::default()
        .build(tauri::generate_context!())
        .expect("Error building app")
        .run(move |_app_handle, event| match event {
            RunEvent::Ready => {
                let (_, child) = app_handle.shell()
                    .sidecar("rekordbot-server")
                    .expect("Failed to create sidecar command")
                    .spawn()
                    .expect("Failed to spawn backend sidecar");
                _ = backend.0.insert(child);
            }
            RunEvent::ExitRequested { .. } => {
                if let Some(child) = backend.0.take() {
                    child.kill().expect("Failed to shutdown backend.");
                }
            }
            _ => {}
        });
}
```

### Zombie Process Prevention

This is a **known pain point** with PyInstaller sidecars specifically. The issue: PyInstaller's `--onefile` mode creates a bootloader process that unpacks and spawns the actual Python process as a child. When Tauri kills the sidecar, it only kills the bootloader PID — the actual Python process can survive as an orphan.

**Mitigation strategies (in order of preference):**

1. **Use PyInstaller `--onedir` mode instead of `--onefile`.** Multiple community reports suggest this avoids the nested-process problem entirely. The trade-off is a directory of files rather than a single executable.

2. **Use the `command_group` crate on the Rust side.** This creates a process group and kills the entire group, including child processes. Several production apps use this approach successfully.

3. **Self-termination watchdog in the Python backend.** The FastAPI server periodically checks if its parent process is still alive. If not, it shuts itself down. This is a belt-and-braces fallback.

4. **Shutdown via HTTP endpoint.** Instead of (or in addition to) process killing, have the Rust side send a shutdown request to the FastAPI server's `/shutdown` endpoint before killing the process. This allows graceful cleanup.

5. **Port-based cleanup on startup.** On app launch, before spawning the sidecar, check if the target port is already in use and kill any lingering processes. This handles the case where a previous crash left an orphan.

**Flag for decision:** There is currently an open feature request for a Tauri Sidecar Lifecycle Management Plugin that would handle all of this — spawning, health checks, auto-restart, graceful shutdown, and cleanup. It doesn't exist yet but shows this is a widely-felt gap. We'll need to build our own lifecycle management.

### Stdout/Stderr Access

Tauri provides full access to the sidecar's stdout and stderr streams via the `CommandEvent` enum. When spawning from Rust, you get a receiver channel that yields `CommandEvent::Stdout(line)` and `CommandEvent::Stderr(line)` events. These can be forwarded to the frontend via Tauri's event system, logged to a file, or both.

This is valuable for debugging and for surfacing backend errors in the UI.

### Alternative Patterns

| Approach | Description | Trade-offs |
|---|---|---|
| **Sidecar (recommended)** | Bundle PyInstaller binary, spawn via Tauri shell plugin | Standard approach. Well-documented. Lifecycle management is manual. |
| **Rust-managed subprocess** | Use `std::process::Command` in Rust instead of the sidecar API | More control over process management. Loses Tauri's bundling and path-resolution helpers. |
| **PyO3 (Python embedded in Rust)** | Run Python code directly inside the Rust process | No separate process to manage. But extremely complex setup with our dependency stack (ffmpeg subprocess calls, librosa/numpy C extensions). Not practical for our use case. |
| **Require Python installed** | Don't bundle Python; require the user to have it | Simplest during development. Terrible UX for distribution. Could be a useful dev-mode shortcut. |

**Recommendation:** Use the sidecar approach for production, with the self-termination watchdog and HTTP shutdown as belt-and-braces. During development, run FastAPI standalone (see Section 2).

---

## 2. Development Workflow

### The Two-Terminal Pattern

The consensus across every Tauri + Python project examined is the same: **in development, you run the Python backend and Tauri frontend as separate processes in separate terminals.**

The reason is straightforward: the sidecar feature expects a compiled binary (via PyInstaller). Recompiling after every Python change would be painfully slow. Instead, you run `uvicorn` directly with `--reload` for hot-reloading.

**Terminal 1 — Python backend:**
```bash
cd backend/
uvicorn main:app --reload --port 8420
```

**Terminal 2 — Tauri + React frontend:**
```bash
npm run tauri dev
# or: cargo tauri dev
```

`tauri dev` starts both the Vite dev server (for React hot-reload) and the Tauri Rust shell. The React frontend gets HMR (hot module replacement) automatically via Vite.

### Hot Reload

- **React frontend:** Full HMR via Vite. Changes appear instantly in the Tauri webview. This works out of the box with `tauri dev`.
- **Python backend:** Hot reload via `uvicorn --reload`. Changes to Python files trigger an automatic server restart (typically < 1 second for a FastAPI app).
- **Rust shell code:** Changes to `src-tauri/src/main.rs` trigger a Rust recompile when running `tauri dev`. This is slow (~10-30 seconds) but should be rare — the Rust code is thin glue.

### Debugging

For Python backend debugging, the standalone development approach is ideal. You can:

- Attach a debugger (VS Code Python debugger, PyCharm, pdb) to the uvicorn process
- Use curl, Postman, or the browser to hit API endpoints directly
- See full Python tracebacks in the terminal
- Run pytest against the backend independently

You should only test the full sidecar integration periodically — perhaps once per phase, or when specifically working on startup/shutdown behaviour.

### Recommended Dev Workflow

```
┌─────────────────────────────────────────────────────┐
│  Day-to-day development:                            │
│                                                     │
│  Terminal 1: uvicorn main:app --reload --port 8420  │
│  Terminal 2: npm run tauri dev                      │
│                                                     │
│  React changes → instant HMR                        │
│  Python changes → uvicorn auto-restarts             │
│  Backend debugging → standard Python tools          │
│  API testing → curl / Postman / pytest              │
├─────────────────────────────────────────────────────┤
│  Periodic integration testing:                      │
│                                                     │
│  1. Build PyInstaller binary                        │
│  2. Copy to src-tauri/binaries/ with target triple  │
│  3. Run full app with sidecar spawning              │
│  4. Test startup, shutdown, error recovery          │
└─────────────────────────────────────────────────────┘
```

### Dev/Production Mode Detection

The frontend needs to know whether to talk to `http://localhost:8420` (dev, standalone uvicorn) or to a dynamically-assigned port (production, sidecar). Options:

**Option A — Build-time flag:** Vite's `import.meta.env.DEV` is `true` during `tauri dev`. Use this to switch the base URL.

**Option B — Tauri passes the port:** In production, the Rust code spawns the sidecar with a specific port argument and passes it to the frontend via a Tauri command or startup event.

Both approaches are common. Option B is more robust for production. They can be combined: use the build flag for dev, and Tauri-provided port for production.

---

## 3. Packaging & Distribution

### PyInstaller Integration

PyInstaller compiles the Python backend (including the Python interpreter, all dependencies, and your code) into a standalone executable that requires no Python installation on the target machine.

**The build pipeline is two separate steps, not integrated:**

1. **Build the Python sidecar** with PyInstaller → produces an executable
2. **Build the Tauri app** with `cargo tauri build` → includes the sidecar executable in the bundle

These are sequenced via build scripts. Tauri's `beforeBuildCommand` in `tauri.conf.json` can invoke the PyInstaller build automatically.

**`--onefile` vs `--onedir`:**

| Mode | Output | Startup Speed | Zombie Risk | Signing |
|---|---|---|---|---|
| `--onefile` | Single executable | Slower (unpacks to temp dir each launch) | Higher (nested process) | Harder on macOS |
| `--onedir` | Directory of files | Faster (no unpacking) | Lower (direct process) | Easier |

**Recommendation:** Use `--onedir` mode. It avoids the zombie process issue, starts faster, and is easier to code-sign. The trade-off is that we bundle a directory rather than a single file, but Tauri handles this transparently.

### Bundle Size Estimates

Based on community reports and similar projects:

| Component | Approximate Size |
|---|---|
| Python interpreter + stdlib | ~30-40 MB |
| FastAPI + uvicorn + dependencies | ~5-10 MB |
| SQLAlchemy | ~5 MB |
| mutagen | ~2 MB |
| numpy (if needed by librosa) | ~30-50 MB |
| librosa | ~15-20 MB |
| aubio | ~2-5 MB |
| Anthropic SDK | ~2-3 MB |
| **Total Python sidecar** | **~90-130 MB** |
| ffmpeg binary | ~70-80 MB |
| Tauri shell + React frontend | ~5-15 MB |
| **Total app bundle** | **~170-230 MB** |

numpy is the biggest wildcard — it's large and pulls in BLAS/LAPACK. If librosa's numpy dependency can be minimised (e.g., using a lighter alternative for specific functions), that could save 30-50 MB. Worth investigating in Phase 2.

**Alternatives to PyInstaller:**

- **Nuitka:** Compiles Python to C, then to native code. Smaller output, faster execution. More complex setup, longer build times, occasional compatibility issues with C-extension packages.
- **cx_Freeze:** Similar to PyInstaller but less widely used. Fewer community resources for troubleshooting.
- **PyInstaller remains the pragmatic choice** for our stack — it has the best out-of-the-box support for numpy, and the most community experience with Tauri integration.

### ffmpeg Bundling

ffmpeg is a separate binary (~70-80 MB). Two viable approaches:

**Option A — Bundle as a second sidecar:**
```json
{
  "bundle": {
    "externalBin": [
      "binaries/rekordbot-server",
      "binaries/ffmpeg"
    ]
  }
}
```
Requires the ffmpeg binary to be named with the target triple suffix (e.g., `ffmpeg-aarch64-apple-darwin`). The Python backend would call it via a path resolved by Tauri.

**Option B — Bundle as a resource:**
```json
{
  "bundle": {
    "resources": ["resources/ffmpeg"]
  }
}
```
Resources are bundled into the app but aren't treated as executables by Tauri's shell system. The Python backend would locate it via a path passed from the Rust layer. This is simpler but means the Python code manages ffmpeg execution directly via `subprocess`.

**Recommendation:** Option B (resource). Our Python backend already plans to call ffmpeg via subprocess, so we don't need Tauri's shell permission system involved. The Rust layer just needs to resolve the resource path and pass it to the Python backend as a startup argument or config value.

### macOS Packaging Concerns

**Code signing:** Required for distribution outside the App Store. All binaries in the bundle (including the PyInstaller output and ffmpeg) must be individually signed. Apple's requirement is to sign "from the inside out" — sign every .dylib and .so first, then the executables, then the .app bundle.

**Notarisation:** Required since macOS 10.14.5. Key requirements:
- All binaries must be signed with a Developer ID certificate
- Hardened Runtime must be enabled
- Python apps need the `com.apple.security.cs.allow-unsigned-executable-memory` entitlement (required because Python's runtime uses JIT-like memory patterns)
- All binaries must be linked against macOS 10.9+ SDK

**Known pain points with PyInstaller + macOS:**
- Signing with `--deep` flag is unreliable; you must sign each binary individually
- numpy and other packages with C extensions can have binaries built against older SDKs, causing notarisation rejection
- PyInstaller's `--onefile` mode has historically had more signing issues than `--onedir`

**Universal binaries (Intel + Apple Silicon):** PyInstaller does not natively produce universal2 binaries. You would need to either: (a) build separate binaries for each architecture and let Tauri select the right one, or (b) use `lipo` to merge two PyInstaller outputs into a universal binary. Option (a) is simpler and is what Tauri's target-triple naming already supports.

**Recommendation:** Target Apple Silicon only for the initial build. Cross-architecture support adds significant complexity and can be tackled later if needed.

### Auto-Update

Tauri v2 has a built-in updater plugin. It works by replacing the entire application bundle — which includes sidecars and resources. So updating the Python backend or ffmpeg is handled automatically as part of a full app update. There is no mechanism for partial/sidecar-only updates. On macOS and Linux, the sidecar/resource locations within the bundle are read-only, so they cannot be updated independently.

This is fine for our use case — we'll ship complete updates.

---

## 4. Frontend-Backend Communication

### Localhost HTTP

The plan to use standard HTTP requests from React to FastAPI over localhost is the right approach. This is what every Tauri + Python template project uses.

**CSP Configuration:** Tauri enforces Content Security Policy headers on the webview. To allow the frontend to make requests to the Python backend, you need to add the backend's origin to the `connect-src` directive:

```json
{
  "security": {
    "csp": {
      "default-src": "'self'",
      "connect-src": "ipc: http://ipc.localhost http://localhost:8420 http://127.0.0.1:8420"
    }
  }
}
```

Include both `localhost` and `127.0.0.1` to avoid resolution inconsistencies across platforms.

**CORS:** The FastAPI backend needs CORS middleware configured to accept requests from the Tauri webview's origin. In production, Tauri serves the frontend from `http://tauri.localhost` (or `https://tauri.localhost` on some platforms). In development, Vite serves from `http://localhost:1420` (or similar). Configure CORS to accept both:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://tauri.localhost",
        "https://tauri.localhost",
        "http://localhost:1420",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Port Management

**Options:**

1. **Hardcoded port (e.g., 8420):** Simplest. Risk of conflict if user is running something else on that port.
2. **OS-assigned port:** Bind to port 0, let the OS assign a free port. The backend reports the actual port via stdout. Rust reads it and passes to the frontend.
3. **Port scanning:** Try a preferred port, increment if busy.

**Recommendation:** Start with a hardcoded port (8420 is uncommon enough). Add port-conflict detection that checks the port on startup and fails with a clear error rather than silently breaking. OS-assigned ports can be added later if needed — they add complexity to the startup handshake.

### Real-Time Progress: WebSocket vs SSE

The app needs real-time progress updates (file conversion, batch processing, AI tagging). The communication is primarily one-directional: server → client.

| Approach | Direction | Complexity | Tauri Support |
|---|---|---|---|
| **SSE (Server-Sent Events)** | Server → Client only | Low | Works with standard `fetch` / `EventSource`. No plugin needed for localhost HTTP. |
| **WebSocket** | Bidirectional | Medium | Tauri has a WebSocket plugin, but for localhost connections the standard browser WebSocket API works fine. |
| **Polling** | Client → Server | Very low | Always works. Wastes resources for frequent updates. |
| **Tauri Events** | Rust ↔ Frontend | Low | Built into Tauri. But requires the Rust layer to be the intermediary. |

**Recommendation:** Use **SSE** for progress reporting. It's perfect for our use case (unidirectional server-push), simpler than WebSocket, has automatic reconnection built into the browser's `EventSource` API, and works natively over localhost HTTP without any Tauri plugins. FastAPI supports SSE natively via `StreamingResponse`.

For the rare case where we need frontend → backend communication (which is just standard REST calls), regular HTTP is fine.

### Tauri IPC — Do We Need It?

Tauri's `invoke` IPC mechanism lets the JavaScript frontend call Rust functions directly. The question is whether to use this alongside or instead of localhost HTTP.

**Use Tauri IPC for:**
- Asking the Rust layer for file paths (app data directory, resource paths)
- Triggering sidecar lifecycle operations (start, stop, health check)
- Accessing native OS features (file dialogs, notifications)
- Passing the backend port to the frontend on startup

**Don't use Tauri IPC for:**
- Business logic (that lives in the Python backend)
- Data queries (those go to FastAPI)
- File processing (Python handles this)

In short: Tauri IPC is the thin glue layer for desktop integration. FastAPI handles all actual application logic. This separation keeps the Rust layer minimal and plays to our Python strengths.

---

## 5. Phase 0 Recommendations

### What Needs To Be In Place

Based on the research above, here's what Phase 0 scaffolding should include beyond what's already in the project plan:

**Tauri configuration:**
- [ ] `tauri.conf.json` with CSP configured for localhost backend access
- [ ] Shell plugin installed and configured with sidecar permissions
- [ ] `beforeDevCommand` set to start the Vite dev server
- [ ] `beforeBuildCommand` set to invoke PyInstaller then the frontend build
- [ ] Capabilities file (`src-tauri/capabilities/default.json`) with sidecar execution permissions

**Rust sidecar lifecycle:**
- [ ] `main.rs` with sidecar spawn on `RunEvent::Ready`
- [ ] Graceful shutdown on `RunEvent::ExitRequested`
- [ ] Health check endpoint polling (hit `/health` until the backend responds before marking ready)
- [ ] Port passed to frontend via Tauri command or window event

**Python backend:**
- [ ] FastAPI app with `/health` endpoint
- [ ] CORS middleware configured for both dev and production origins
- [ ] `if __name__ == "__main__"` block using uvicorn for both dev and PyInstaller modes
- [ ] Configurable port via CLI argument

**Build tooling:**
- [ ] PyInstaller spec file or build script for the Python backend
- [ ] Script to rename PyInstaller output with correct target triple
- [ ] `Makefile` or `package.json` scripts for common operations:
  - `make dev` → starts both terminals (or instructions for two-terminal setup)
  - `make build-backend` → PyInstaller build + rename
  - `make build` → full production build
  - `make test` → runs pytest

### Folder Structure Adjustments

The sidecar pattern requires a `binaries/` directory inside `src-tauri/` for the compiled Python binary. Adjusted structure:

```
rekordbot/
├── CLAUDE.md
├── SESSIONS.md
├── README.md
├── Makefile
├── pyproject.toml
├── backend/
│   ├── main.py              ← FastAPI entry point
│   ├── models/
│   ├── services/
│   ├── routes/
│   └── tests/
├── frontend/
│   ├── src/
│   ├── package.json
│   ├── vite.config.ts
│   └── src-tauri/
│       ├── src/
│       │   └── main.rs      ← Sidecar lifecycle management
│       ├── binaries/         ← PyInstaller output goes here (gitignored)
│       ├── resources/        ← ffmpeg binary goes here (gitignored)
│       ├── capabilities/
│       │   └── default.json  ← Sidecar permissions
│       ├── icons/
│       ├── tauri.conf.json
│       └── Cargo.toml
├── scripts/
│   ├── build-backend.sh      ← PyInstaller + rename
│   └── dev-setup.sh
└── docs/
    ├── features/
    └── architecture.md
```

The `binaries/` and `resources/` directories should be gitignored — they contain large compiled binaries that are build artifacts, not source code.

### Dev Tooling

**VS Code workspace settings** (`.vscode/launch.json`):
- Python debug config targeting `backend/main.py` with uvicorn
- Task to run `tauri dev`

**Makefile targets:**

```makefile
.PHONY: dev-backend dev-frontend build-backend build test

dev-backend:
	cd backend && uvicorn main:app --reload --port 8420

dev-frontend:
	cd frontend && npm run tauri dev

build-backend:
	cd backend && pyinstaller --onedir --name rekordbot-server main.py
	./scripts/rename-sidecar.sh

build: build-backend
	cd frontend && npm run tauri build

test:
	cd backend && pytest
```

---

## 6. Risk Register

| Risk | Severity | Likelihood | Mitigation |
|---|---|---|---|
| **Zombie Python processes after crash** | High | High (with `--onefile`) | Use `--onedir` mode. Implement self-termination watchdog. Port-based cleanup on startup. |
| **PyInstaller + macOS code signing/notarisation** | High | Medium | Budget time for signing pipeline. Use `--onedir`. Test notarisation early (Phase 0 or 1). Need Apple Developer account ($99/year). |
| **CSP blocking frontend-backend requests** | Medium | High (easy to misconfigure) | Set up and test CSP in Phase 0. Include both `localhost` and `127.0.0.1`. |
| **Port conflicts in production** | Medium | Low | Hardcode an uncommon port. Add conflict detection on startup. Provide clear error message. |
| **Large bundle size (~200 MB)** | Low | Certain | Acceptable for a desktop app. Can optimise later (exclude unused numpy submodules, use UPX compression). |
| **PyInstaller build breaks with new deps** | Medium | Medium | Add PyInstaller build to CI early. Test after adding any new Python dependency. Some packages need hidden imports or hook files. |
| **Mixed content (HTTPS/HTTP) on Windows** | Medium | Low-Medium | On Windows, Tauri's webview may serve from HTTPS, blocking requests to HTTP localhost. Test on Windows early. May need Tauri's localhost plugin or WebSocket as fallback. |
| **Dev/production mode mismatch** | Low | Medium | Keep the dev and production code paths as similar as possible. The only difference should be how the backend URL is resolved. |
| **Tauri v2 still evolving** | Low | Low | Pin Tauri version. Monitor release notes. The sidecar API is stable. |
| **ffmpeg dynamic library issues on macOS** | Medium | Medium | Use a statically-linked ffmpeg build. Test the bundled ffmpeg binary on a clean macOS install (no Homebrew). |

### Highest-Priority Actions

1. **Get the two-terminal dev workflow running in Phase 0.** This unblocks everything else.
2. **Test PyInstaller build + sidecar spawn early.** Don't leave this until Phase 6. The first integration test should happen at the end of Phase 0.
3. **If targeting macOS distribution, get an Apple Developer account now** and test code signing + notarisation with a minimal PyInstaller binary. The process is notoriously painful and time-consuming to debug.

---

## Decisions To Make Back In Main Chat

1. **`--onefile` vs `--onedir` for PyInstaller** — Research strongly favours `--onedir`. Confirm.
2. **ffmpeg as sidecar vs resource** — Research recommends resource. Confirm.
3. **Port strategy** — Hardcoded 8420 with conflict detection vs dynamic assignment.
4. **SSE vs WebSocket for progress** — Research recommends SSE. Confirm.
5. **Apple Silicon only vs universal binary for initial build** — Research recommends Apple Silicon only to start.
6. **When to first test the full sidecar integration** — End of Phase 0 recommended.

---

*Document produced from Tauri v2 official documentation, GitHub discussions, community templates (dieharders/example-tauri-v2-python-server-sidecar, guilhermeprokisch/tauri-fastapi-react-app, fudanglp/tauri-fastapi-full-stack-template), and developer blog posts. Information flagged as uncertain where based on community experience rather than official sources.*
