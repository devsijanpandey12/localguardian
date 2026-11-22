# LocalGuardian

**Voice-Driven Local LLM Agent for Sandboxed Windows OS and Browser Automation**

LocalGuardian lets you control Windows (display brightness, volume, allowlisted apps) and **Google Chrome** (#1 priority browser) using natural voice or text commands—powered 100% locally (`faster-whisper` on CPU + Ollama `qwen3:4b` on GPU) behind a **hard-coded Python safety sandbox** that can never touch `C:\Windows`, `C:\Program Files`, Registry, or raw PowerShell.

---

## Tech Stack & Local Models Used

| Layer | Technology / Model | Purpose |
| :--- | :--- | :--- |
| **Language & Environment** | Python 3.11 + Anaconda (`localguardian` env) | Clean Windows dependency isolation (`pyproject.toml` + `environment.yml`) |
| **Voice Input (CPU)** | `sounddevice` + `numpy` + **`faster-whisper`** (`base.en`, `int8`, CTranslate2) | 100% offline speech-to-text on CPU—keeps all GPU VRAM free for the LLM |
| **Tier-1 Fast Router (CPU)** | Pure Python Deterministic Fast Grammar (`fast_grammar.py`) | Sub-millisecond execution for direct commands (brightness, volume, Chrome search, apps) |
| **Tier-2 Local LLM (GPU)** | **Ollama** (`http://127.0.0.1:11434/v1`) + **`qwen3:4b`** (`Q4_K_M`, GGUF, ~3 GB VRAM) via `httpx` | Local multi-step reasoning & native tool calling with `<think>` stripping and JSON repair (tested on RTX 4050 6 GB VRAM) |
| **Browser Automation (#1)** | **Playwright (`channel="chrome"`)** + native Chrome launcher fallback | Drives installed **Google Chrome** first via semantic DOM locators (Edge/Chromium only if Chrome is absent) |
| **Windows OS Controls** | `screen-brightness-control` (WMI / DDC-CI), `pycaw` + `comtypes` (Core Audio), `pywin32`, `ctypes` | Typed native Windows brightness, volume/mute, battery status, and allowlisted app launching (`shell=False`) |
| **Tool Protocol (MCP)** | Official **`mcp` Python SDK** (`MCPServer` on `mcp 2.x`, `FastMCP` v1 fallback) | Exposes all safety-gated Windows & Chrome tools over `stdio` for external MCP clients |
| **Safety, Validation & Audit** | **Pydantic v2**, `PyYAML`, `sqlite3`, `Tkinter` | Hard-coded OS/Program Files/Registry/secret/hotkey/URL blocks, strict schemas, confirmation modal, emergency failsafe, and local SQLite audit log |
| **Testing** | `pytest` + `pytest-asyncio` | 74 automated tests covering adversarial safety attacks, grammar, LLM JSON repair, MCP, and end-to-end orchestration |

---

## Documentation

- [PROTOTYPE.md](./PROTOTYPE.md) — Exact breakdown of what is built in this prototype and why each library/model was chosen.
- [FLOWCHART_RESEARCH.md](./FLOWCHART_RESEARCH.md) — End-to-end architecture, safety decision tree, and sequence flowcharts.
- [RESEARCH.md](./RESEARCH.md) — Full research blueprint, SOTA model comparisons, hardware profiles, and roadmap.

---

## Setup (Windows + Anaconda)

```powershell
# 1. Create and activate the Conda environment
conda create -n localguardian python=3.11 -y
conda activate localguardian

# 2. Install LocalGuardian with Chrome, MCP, voice, and dev tools
pip install -e ".[browser,mcp,dev]" faster-whisper sounddevice numpy

# 3. Install Ollama and pull the default local LLM (fits comfortably on 6 GB VRAM)
winget install -e --id Ollama.Ollama
ollama pull qwen3:4b
```

---

## How to Run

### Option A: Regular PowerShell (Zero Setup via `run.ps1`)
Works even if `conda` is not on your PowerShell `PATH`:

```powershell
.\run.ps1 --doctor        # Verify safety blocks, Chrome, APIs, and Ollama
.\run.ps1 --models        # Show active LLM, quantization, GPU VRAM, and voice STT
.\run.ps1 --text          # Interactive live text mode (add --dry-run to simulate)
.\run.ps1 --voice         # Push-to-talk local voice mode (faster-whisper CPU + Qwen3 GPU)
.\run.ps1 --once "go to Chrome and type Elon Musk"
.\run.ps1 --audit         # View recent SQLite audit log entries
.\run.ps1 --mcp           # Start MCP stdio server
```

### Option B: Anaconda Prompt
```powershell
conda activate localguardian

localguardian --doctor
localguardian --models
localguardian --text --dry-run
localguardian --text
localguardian --voice
localguardian --audit
localguardian --mcp
pytest
```

### Example Commands to Try
- `Windows, increase the brightness` / `set brightness to 70`
- `decrease volume by 15` / `mute` / `unmute`
- `go to Chrome and type Elon Musk`
- `it feels way too dark in here, brighten the screen a bit and also look up SpaceX in the browser` *(Tier-2 `qwen3:4b`)*
- `delete C:\Windows\System32` / `run powershell` *(watch the hard safety block + audit log)*

---

## Core Safety Guarantees

- Runs as a **standard non-admin user** (never requests UAC elevation).
- **Zero raw PowerShell/cmd execution**—the LLM only sees narrow, strictly typed Python tools.
- Hard-coded blocks on `C:\Windows`, `C:\Program Files`, `C:\Program Files (x86)`, `C:\ProgramData`, `AppData`, Windows Registry, credential stores, unsafe URL schemes (`file://`, `chrome://`, `javascript:`), and OS hotkeys (`Win+*`, `Alt+F4`, `Ctrl+Alt+Del`).
- Every command and policy decision is logged locally to `~/.localguardian/audit.db` (`localguardian --audit`).

## License

MIT — see [LICENSE](./LICENSE).
