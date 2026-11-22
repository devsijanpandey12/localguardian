# LocalGuardian Prototype — What Was Built & Why Each Choice Was Made

> **Scope:** Unlike [RESEARCH.md](./RESEARCH.md) (broader SOTA landscape & future roadmap) and [FLOWCHART_RESEARCH.md](./FLOWCHART_RESEARCH.md) (full target flowcharts), this document records **strictly what is implemented right now in Prototype v0.1**, the exact libraries and models used, and the engineering rationale behind every choice.

---

## 1. Prototype Runtime Environment

| Component | What We Used | Why We Chose It |
| :--- | :--- | :--- |
| **Python Environment** | Dedicated Anaconda env `localguardian` (`Python 3.11.18`) | Isolates Windows COM/audio (`pycaw`, `pywin32`), Playwright, and Whisper dependencies cleanly without touching the base Anaconda install. Python 3.11 has universal prebuilt Windows wheels for every package in our stack. |
| **Packaging** | `pyproject.toml` (`setuptools`, `src/` layout) + `environment.yml` | Standard open-source Python packaging so `pip install -e .` installs the `localguardian` CLI command directly and prevents accidental relative-import bugs. |
| **Configuration** | `PyYAML` + `Pydantic v2` (`src/localguardian/config.py`, `config/default_config.yaml`) | Gives human-readable YAML defaults (`browser.priority: chrome`, `llm.model: qwen3:4b`, `voice.stt_device: cpu`) with strict type validation at startup. |

---

## 2. Hard Safety Core (`src/localguardian/safety/`)

The safety core was built **first**, before any tool execution code, as an independent layer outside the LLM.

| File | What Was Built | Why We Designed It This Way |
| :--- | :--- | :--- |
| `safety/policy.py` | Immutable `SafetyPolicy` engine with hard-coded denylists (`C:\Windows`, `C:\Program Files`, `C:\Program Files (x86)`, `C:\ProgramData`, `%APPDATA%`, `%LOCALAPPDATA%`, Registry hives, `.ssh`/`.env`/`.pem`/`.key`, `~/.localguardian`), forbidden shell/binary blocklists (`run_powershell`, `cmd.exe`, `regedit`, `diskpart`), executable write block (`.exe`, `.ps1`, `.bat`, `.reg`, etc.), strict URL validator (`http`/`https` only), hotkey blacklist (`Win`, `Alt+F4`, `Ctrl+Alt+Del`), and 4-tier risk classification (`SAFE`, `MEDIUM`, `HIGH`, `FORBIDDEN`). | **Never trust LLM system prompts for security.** Small local models can hallucinate or suffer prompt injection from web content. Hard-coding protected Windows directories and canonicalizing paths via `Path.resolve(strict=False)` defeats `..\..\Windows` traversal and guarantees system/program files can never be corrupted—even if someone misconfigures YAML. |
| `safety/confirm.py` | `ConfirmationManager` supporting desktop Tkinter Yes/No modal (`DIALOG`), terminal prompt (`CLI`), and fail-closed `DENY` mode. | Any `MEDIUM`/`HIGH` risk action requires explicit human sign-off; using built-in `tkinter` avoids heavy GUI framework overhead in v0.1. |
| `safety/audit.py` | Local SQLite append-only log (`~/.localguardian/audit.db`) via Python's built-in `sqlite3`. | Zero external database setup; lets you inspect every spoken command, routing tier, policy rule ID, and blocked attempt (`localguardian --audit`). |
| `safety/failsafe.py` | Thread-safe `FailsafeController` with manual abort flag and Win32 `GetCursorPos` top-left corner-slam check. | Provides an instant physical human override independent of the LLM loop. |

---

## 3. Typed Windows OS & Google Chrome Tools (`src/localguardian/tools/`)

Instead of giving the model arbitrary PowerShell access, every capability is exposed as a narrow, Pydantic-validated Python function routed through one central chokepoint.

| File | Libraries Used | Why We Chose Them |
| :--- | :--- | :--- |
| `tools/registry.py` | `Pydantic v2` + `ToolRegistry` | Single mandatory pipeline: **Failsafe → `SafetyPolicy.evaluate()` → Pydantic schema check → Dry-Run / Confirmation → Execute → Audit Log**. Also auto-exports OpenAI-compatible JSON schemas so Ollama never even sees forbidden tools. |
| `tools/os_controls.py` | `screen-brightness-control`, `pycaw` + `comtypes`, `pywin32`, `ctypes` Win32 `GetSystemPowerStatus`, `subprocess.Popen(..., shell=False)` | • `screen-brightness-control` talks natively to Windows WMI / DDC-CI without shelling out.<br>• `pycaw` controls Windows Core Audio directly.<br>• Allowlisted app launches strictly use `shell=False` against verified executable paths so command injection is impossible.<br>• `get_system_status` gives a safe, read-only check of brightness, volume, and battery. |
| `tools/browser.py` | **Playwright (`channel="chrome"`)** with native Chrome fallback | **Google Chrome is locked as Priority #1.** Playwright drives your real installed Chrome via DOM selectors (far faster and more reliable than pixel clicking) and keeps the Chrome session alive during interactive runs so follow-up commands reuse the same window. Edge/Chromium is only touched if Chrome is absent. |

---

## 4. Local Cognitive Cascade & MCP (`src/localguardian/brain/`, `mcp_server.py`)

| File | Model / Library Used | Why We Chose Them |
| :--- | :--- | :--- |
| `brain/fast_grammar.py` | Pure Python regex fast-path (`FastGrammarParser`) | Handles common direct commands (*"Windows, increase the brightness"*, *"go to Chrome and type Elon Musk"*, volume, mute, open apps) in **<1 ms on CPU**—zero GPU spin-up and works even when Ollama isn't running. Also catches explicit unsafe phrases (*"delete C:\Windows"*, *"run powershell"*) and routes them into `SafetyPolicy` so you get an explicit, audited block. |
| `brain/llm_planner.py` | **`httpx` → Ollama (`qwen3:4b`)** on RTX 4050 GPU + custom multi-stage JSON repair | **Why `Qwen3` (`qwen3:4b` default, `qwen3:8b` optional)?** Qwen3 currently leads open-weight small models in structured function calling and strict JSON tool-use accuracy while fitting comfortably inside your **RTX 4050's 6 GB VRAM** (~2.6 GB for `4b` Q4_K_M). The custom parser strips Qwen3's `<think>...</think>` reasoning blocks and repairs minor JSON quirks (markdown fences, trailing commas) so small local models stay reliable. |
| `brain/orchestrator.py` | `LocalGuardianOrchestrator` | Clean 2-tier cascade: tries Tier-1 fast grammar first, escalates to Tier-2 Ollama only when natural phrasing or multi-step reasoning is needed, and halts immediately if any step hits a safety block. |
| `mcp_server.py` | Official **`mcp` Python SDK (`MCPServer` on `mcp 2.x`, with `FastMCP` v1 fallback)** over `stdio` | Wraps the exact same `ToolRegistry` with `@mcp.tool()` decorators (~95 lines of code). This makes LocalGuardian's sandboxed Windows & Chrome controls immediately usable by external MCP clients (LM Studio, Claude Desktop, VS Code, Cursor) with zero duplicated safety logic. |

---

## 5. Local Voice Pipeline (`src/localguardian/voice/`)

| File | Model / Library Used | Why We Chose Them |
| :--- | :--- | :--- |
| `voice/stt.py` | **`faster-whisper` (`base.en`, `device="cpu"`, `compute_type="int8"`)** | Runs 100% offline on your **Ryzen 7 7840HS CPU** (CTranslate2 `int8`, ~250 MB RAM, sub-second transcription). Running STT on CPU keeps **100% of your RTX 4050's 6 GB VRAM dedicated to `qwen3:4b`**. |
| `voice/listener.py` | **`sounddevice` + `numpy`** (16 kHz mono float32, Push-to-Talk) | Reliable cross-device Windows audio capture without requiring C++ PortAudio compilation headaches (`PyAudio` often fails to build on Windows). Push-to-talk lets you immediately test real voice → Chrome/brightness execution cleanly before adding always-on `openWakeWord` in v0.2. |

---

## 6. CLI & Verification (`src/localguardian/cli.py`, `tests/`)

- **`localguardian --doctor`** — One-command diagnostic confirming non-admin privilege, live safety blocks, Chrome installation, OS/browser/voice packages, and Ollama availability.
- **`localguardian --text [--dry-run]`** — Interactive terminal console for immediate safe testing.
- **`localguardian --voice [--dry-run]`** — Local microphone voice mode.
- **`localguardian --once "<cmd>"`** — Single-command execution.
- **`localguardian --mcp`** — Starts the FastMCP stdio server.
- **`localguardian --audit`** — Prints recent entries from `~/.localguardian/audit.db`.
- **Automated Test Suite (`tests/`):**
  - `tests/test_safety_policy.py` — Adversarial path, traversal, Registry, credential, executable, shell, app, URL scheme, and hotkey block tests.
  - `tests/test_fast_grammar.py` — Deterministic command parsing and escalation tests.
  - `tests/test_llm_planner.py` — Qwen3 `<think>` stripping, malformed JSON repair, and native `tool_calls` tests.
  - `tests/test_orchestrator_e2e.py` — Full cascade + dry-run + adversarial block + SQLite audit tests.

---

## 7. Planned Next Additions (Post-Prototype v0.1)

These items from [FLOWCHART_RESEARCH.md](./FLOWCHART_RESEARCH.md) plug directly into the existing modular layers without changing the core architecture:
1. Hands-free wake word (`openWakeWord` + `Silero VAD`) inside `voice/listener.py`.
2. Optional `Cactus Needle 3` fast router between `fast_grammar.py` and `llm_planner.py`.
3. Windows UI Automation (`pywinauto`) for interacting with arbitrary non-Chrome desktop apps + optional vision fallback (`Cactus Mirage` / `OmniParser`).
4. Minimal always-on-top system tray / floating HUD showing live transcripts, safety verdicts, and one-click undo.
