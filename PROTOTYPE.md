# LocalGuardian Prototype (v0.2.0) — What Was Built & Why Each Choice Was Made

> **Scope:** Unlike [RESEARCH.md](./RESEARCH.md) (broader SOTA landscape & roadmap), this document records **strictly what is implemented and verified right now in v0.2.0**, the exact libraries and local models used, and the engineering rationale behind every choice.

---

## 1. Runtime Environment & Launchers

| Component | What We Used | Why We Chose It |
| :--- | :--- | :--- |
| **Python Environment** | Dedicated Anaconda env `localguardian` (`Python 3.11.18`) | Isolates Windows COM/audio (`pycaw`, `pywin32`), `cactus-compute`, Playwright, and `faster-whisper` cleanly without touching base Anaconda. |
| **Packaging** | `pyproject.toml` (`setuptools`, `src/` layout) + `environment.yml` + `run.ps1` | Standard Python package install (`localguardian` CLI) plus a zero-setup PowerShell launcher (`.\run.ps1`) so regular PowerShell works even when `conda` is not on `PATH`. |
| **Configuration** | `PyYAML` + `Pydantic v2` (`config/default_config.yaml`, `src/localguardian/config.py`) | Strongly typed configuration for all 3 cascade tiers, Chrome #1 priority, Needle confidence threshold, and allowlisted apps. |

---

## 2. Hard Safety Core (`src/localguardian/safety/`)

Built **first** as a deterministic Python wall completely independent of both Cactus Needle and Qwen3.

| File | What Was Built | Why We Designed It This Way |
| :--- | :--- | :--- |
| `safety/policy.py` | Immutable `SafetyPolicy` with hard-coded denylists (`C:\Windows`, `C:\Program Files`, `C:\Program Files (x86)`, `C:\ProgramData`, `%APPDATA%`, `%LOCALAPPDATA%`, Registry hives, `.ssh`/`.env`/`.pem`/`.key`, `~/.localguardian`), forbidden shell/binary blocklists (`run_powershell`, `cmd.exe`, `regedit`, `diskpart`), executable write blocks, strict URL scheme validation (`http`/`https` only), screenshot filename traversal blocking, media/snap/mode enum enforcement, hotkey blacklist (`Win`, `Alt+F4`, `Ctrl+Alt+Del`), and 4-level risk tiers. | **Never trust LLM or edge-model prompts for security.** Even if Cactus Needle or Qwen3 gets confused or sees prompt-injected text in Chrome, `SafetyPolicy.evaluate()` runs in deterministic Python before any OS/file API executes. |
| `safety/confirm.py` | `ConfirmationManager` (`Tkinter` desktop modal, CLI prompt, fail-closed `DENY`). | Explicit human approval for `MEDIUM`/`HIGH` actions with zero extra GUI dependencies. |
| `safety/audit.py` | Local SQLite audit log (`~/.localguardian/audit.db`) via built-in `sqlite3`. | Records every transcript, routing tier (`tier1_grammar`, `tier1_5_cactus_needle`, `tier2_ollama`, `mcp`), tool call, policy rule ID, and outcome (`.\run.ps1 --audit`). |
| `safety/failsafe.py` | Thread-safe abort flag + Win32 top-left corner-slam failsafe. | Instant physical human override independent of model execution. |

---

## 3. True 3-Tier Local Cognitive Cascade (`src/localguardian/brain/`)

| Tier & File | Model / Library | Latency & Hardware | Why We Structured the Cascade This Way |
| :--- | :--- | :--- | :--- |
| **Tier 1:** `fast_grammar.py` | Pure Python regex grammar | **<1 ms** (CPU, 0 VRAM) | Exact direct commands (*"Windows, increase the brightness"*, *"put chrome on the left"*, *"pause music"*) execute instantly with 100% predictability; explicit unsafe phrases (*"delete C:\Windows"*, *"run powershell"*) route straight to `SafetyPolicy` for audited refusal. |
| **Tier 1.5:** `needle_router.py` | **`cactus-compute` v4.2.6 (`cactus.Needle`)** (`min_confidence=0.65`, `CACTUS_TELEMETRY=0`) | **~70–130 ms** (CPU, ~131 MB RAM, 0 VRAM) | **Empirical design insight:** Live benchmarking showed Needle 3 excels at compact, grounded single-step tool calls (e.g., `set_volume(40)` at 0.90 conf in 72 ms, `open_app("notepad")` at 0.81 conf in 113 ms, `chrome_search` at 0.75 conf in 128 ms) while dropping to low confidence (0.05–0.43) on ambiguous or multi-step prompts. Giving Needle a compact 6-tool schema + `min_confidence=0.65` gate yields fast CPU routing with clean escalation to Tier 2. |
| **Tier 2:** `llm_planner.py` | **`httpx` → Ollama `qwen3:4b`** (`Q4_K_M`, GGUF) | **~8–12 s** (RTX 4050 GPU, ~3.0 GB VRAM) | Handles messy multi-step reasoning (*"my eyes hurt, lower brightness a bit and look up SpaceX in Chrome"*) with full access to all 17 safe tools. Includes `<think>` / orphan `</think>` stripping and multi-stage JSON repair. |
| **Orchestrator:** `orchestrator.py` | `LocalGuardianOrchestrator` | — | Runs `Tier 1 → Tier 1.5 (confidence-gated) → Tier 2`, captures `needle_trace` (confidence, latency, RAM), and stops any multi-step chain immediately on a safety block. |

---

## 4. Typed Windows OS, Window Management & Chrome Tools (`src/localguardian/tools/`)

All 17 tools pass through one mandatory chokepoint (`tools/registry.py`: Failsafe → `SafetyPolicy` → Pydantic Schema → Dry-Run/Confirm → Execute → SQLite Audit).

| File | Tools & Libraries | Why We Chose Them |
| :--- | :--- | :--- |
| `tools/os_controls.py` | • **Brightness:** `screen-brightness-control` (WMI / DDC-CI)<br>• **Audio:** `pycaw` + `comtypes` (Windows Core Audio)<br>• **Media Playback:** Win32 `keybd_event` (`VK_MEDIA_PLAY_PAUSE`, `NEXT`, `PREV`)<br>• **Allowlisted Apps:** `subprocess.Popen(..., shell=False)`<br>• **Sandboxed Screenshots:** `Pillow.ImageGrab` strictly inside `~/LocalGuardian_Workspace/screenshots/`<br>• **Workspace Presets:** `coding`, `study`, `focus`, `relax`<br>• **Read-Only System Diagnostics:** `psutil` (CPU/RAM/top processes) + Win32 battery + read-only `nvidia-smi` GPU temp/VRAM | Narrow, typed native APIs eliminate shell injection entirely while delivering genuinely useful day-to-day desktop control and live hardware health visibility. |
| `tools/window_tools.py` | `list_open_windows`, `focus_window`, `snap_window` (`left`, `right`, `maximize`, `minimize`) via Win32 `ctypes` (`EnumWindows`, `SystemParametersInfoW` `SPI_GETWORKAREA`, `MoveWindow`) | Uses the real desktop work area (excluding the taskbar) and runs strictly under standard-user UIPI so elevated/UAC windows can never be touched. |
| `tools/browser.py` | **Playwright (`channel="chrome"`)** + native Chrome launcher fallback | **Google Chrome is Priority #1.** Drives real installed Chrome cleanly via semantic DOM locators; falls back to Edge/Chromium only if Chrome is not installed. |
| `mcp_server.py` | Official **`mcp` SDK (`MCPServer` on `mcp 2.x`, `FastMCP` v1 fallback)** | Exposes all 17 safety-gated tools over `stdio` (`.\run.ps1 --mcp`) so LM Studio, Claude Desktop, VS Code, or Cursor can reuse LocalGuardian's sandboxed hands directly. |

---

## 5. Dual Offline CPU Voice Stack (`src/localguardian/voice/`)

| File | Backends & Libraries | Why We Chose Them |
| :--- | :--- | :--- |
| `voice/stt.py` | **`faster-whisper`** (`base.en`, CPU `int8`, default) **+ `cactus.Whistle`** (~16.9 MB ultra-light CPU ASR via `--stt whistle`) | Both run **100% on your Ryzen 7 CPU**, keeping all 6 GB of RTX 4050 VRAM free for `qwen3:4b`. `faster-whisper` gives stronger general English accuracy; `Cactus Whistle` gives an ultra-small 16.9 MB footprint. |
| `voice/listener.py` | `sounddevice` + `numpy` (16 kHz mono float32, Push-to-Talk) | Clean prebuilt Windows wheels (no PortAudio C++ compile pain) and reliable push-to-talk capture verified on your Realtek Microphone Array. |
