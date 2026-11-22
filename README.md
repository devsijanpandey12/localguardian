# LocalGuardian

**Voice-Driven Local LLM Agent for Sandboxed Windows OS and Browser Automation**

LocalGuardian lets you control Windows (display brightness, volume, allowlisted apps) and **Google Chrome** (#1 priority browser) using natural voice or text commands—powered 100% locally (`faster-whisper` on CPU + Ollama `qwen3:4b` on GPU) behind a **hard-coded Python safety sandbox** that can never touch `C:\Windows`, `C:\Program Files`, Registry, or raw PowerShell.

---

## Tech Stack & Local Models Used (Prototype v0.1)

| Layer | Technology / Model | Purpose |
| :--- | :--- | :--- |
| **Language & Environment** | Python 3.11 + Anaconda (`localguardian` env) | Clean Windows dependency isolation (`pyproject.toml` + `environment.yml`) |
| **Voice Input (CPU)** | `sounddevice` + `numpy` + **`faster-whisper`** (`base.en`, `int8`, CTranslate2) | 100% offline speech-to-text on CPU—keeps all GPU VRAM free for the LLM |
| **Tier-1 Fast Router (CPU)** | Pure Python Deterministic Fast Grammar (`fast_grammar.py`) | Sub-millisecond execution for direct commands (brightness, volume, Chrome search, apps). *(Note: Cactus Needle 3 is planned as an optional Tier-1.5 upgrade, not used in v0.1.)* |
| **Tier-2 Local LLM (GPU)** | **Ollama** (`http://127.0.0.1:11434/v1`) + **`qwen3:4b`** (`Q4_K_M`, GGUF, ~3 GB VRAM) via `httpx` | Local multi-step reasoning & native tool calling with `<think>` stripping and JSON repair (tested on RTX 4050 6 GB VRAM) |
| **Browser Automation (#1)** | **Playwright (`channel="chrome"`)** + native Chrome launcher fallback | Drives installed **Google Chrome** first via semantic DOM locators (Edge/Chromium only if Chrome is absent) |
| **Windows OS Controls** | `screen-brightness-control` (WMI / DDC-CI), `pycaw` + `comtypes` (Core Audio), `pywin32`, `ctypes` | Typed native Windows brightness, volume/mute, battery status, and allowlisted app launching (`shell=False`) |
| **Tool Protocol (MCP)** | Official **`mcp` Python SDK** (`MCPServer` on `mcp 2.x`, `FastMCP` v1 fallback) | Exposes all safety-gated Windows & Chrome tools over `stdio` for external MCP clients |
| **Safety, Validation & Audit** | **Pydantic v2**, `PyYAML`, `sqlite3`, `Tkinter` | Hard-coded OS/Program Files/Registry/secret/hotkey/URL blocks, strict schemas, confirmation modal, emergency failsafe, and local SQLite audit log |
| **Testing** | `pytest` + `pytest-asyncio` | 74 automated tests covering adversarial safety attacks, grammar, LLM JSON repair, MCP, and end-to-end orchestration |

---

## Step-by-Step Guide: How to Install & Run (Windows 10 / 11)

### Step 1: Clone the Repository
```powershell
git clone https://github.com/devsijanpandey12/localguardian.git
cd localguardian
```

### Step 2: Create & Activate the Dedicated Anaconda Environment
Open **Anaconda Prompt** and run:
```powershell
conda create -n localguardian python=3.11 -y
conda activate localguardian
```

### Step 3: Install LocalGuardian & Dependencies
Inside the activated `localguardian` environment:
```powershell
pip install -e ".[browser,mcp,dev]" faster-whisper sounddevice numpy
```

### Step 4: Install Ollama & Pull the Local LLM (`qwen3:4b`)
*(Needed for natural/multi-step Tier-2 commands; direct Tier-1 commands already work without Ollama.)*
```powershell
winget install -e --id Ollama.Ollama
```
Start Ollama (launch **Ollama** from the Windows Start Menu, or run `ollama serve` in a separate terminal), then pull the model:
```powershell
ollama pull qwen3:4b
```

### Step 5: Verify Setup, Safety Guardrails & Active Models
From **regular PowerShell** (works even if `conda` is not on your `PATH`):
```powershell
.\run.ps1 --doctor
.\run.ps1 --models
```
*(Or in **Anaconda Prompt** after `conda activate localguardian`: `localguardian --doctor` and `localguardian --models`.)*

You should see `[OK  ]` for Python 3.11, `Admin privilege: False`, all 6 safety checks, Google Chrome, OS/voice libraries, and `Ollama Status: ONLINE`.

### Step 6: Run LocalGuardian

**Safe dry-run test first (simulates actions without changing Windows):**
```powershell
.\run.ps1 --text --dry-run
```

**Live interactive text mode:**
```powershell
.\run.ps1 --text
```

**Live push-to-talk local voice mode (`faster-whisper` on CPU + `qwen3:4b` on GPU):**
```powershell
.\run.ps1 --voice
```
*(Press **Enter** to start recording → speak your command → press **Enter** again to transcribe and execute. First voice run downloads the ~140 MB `base.en` Whisper model once.)*

**Single one-shot command:**
```powershell
.\run.ps1 --once "Windows, increase the brightness"
.\run.ps1 --once "go to Chrome and type Elon Musk"
```

### Step 7: Inspect Audit Logs, Run Tests, or Start MCP Server
```powershell
# View every executed and blocked command logged to ~/.localguardian/audit.db
.\run.ps1 --audit

# Run all 74 automated tests (including adversarial safety checks)
& "$env:USERPROFILE\anaconda3\envs\localguardian\python.exe" -m pytest -v

# Expose LocalGuardian's sandboxed tools as an MCP stdio server
.\run.ps1 --mcp
```

---

## Example Commands to Try

- **Fast Tier-1 (CPU, instant):**
  - `Windows, increase the brightness` / `set brightness to 70`
  - `increase volume` / `decrease volume by 15` / `mute` / `unmute`
  - `go to Chrome and type Elon Musk`
  - `open github.com in chrome` / `open notepad` / `check system status`
- **Multi-Step Tier-2 (`qwen3:4b` on GPU):**
  - `it feels way too dark in here, brighten the screen a bit and also look up SpaceX in the browser`
- **Safety Guardrail Tests (Hard-Blocked + Audited):**
  - `delete C:\Windows\System32`
  - `modify C:\Program Files`
  - `run powershell`
  - `open file:///C:/Windows/win.ini in chrome`

---

## Documentation

- [PROTOTYPE.md](./PROTOTYPE.md) — Exact breakdown of what is built in v0.1 and why each library/model was chosen.
- [FLOWCHART_RESEARCH.md](./FLOWCHART_RESEARCH.md) — End-to-end architecture, safety decision tree, and sequence flowcharts.
- [RESEARCH.md](./RESEARCH.md) — Full research blueprint, SOTA model comparisons (including Cactus Needle/Whistle/Mirage), hardware profiles, and roadmap.

## Core Safety Guarantees

- Runs as a **standard non-admin user** (never requests UAC elevation).
- **Zero raw PowerShell/cmd execution**—the LLM only sees narrow, strictly typed Python tools.
- Hard-coded blocks on `C:\Windows`, `C:\Program Files`, `C:\Program Files (x86)`, `C:\ProgramData`, `AppData`, Windows Registry, credential stores, unsafe URL schemes (`file://`, `chrome://`, `javascript:`), and OS hotkeys (`Win+*`, `Alt+F4`, `Ctrl+Alt+Del`).
- Every command and policy decision is logged locally to `~/.localguardian/audit.db` (`.\run.ps1 --audit`).

## License

MIT — see [LICENSE](./LICENSE).
