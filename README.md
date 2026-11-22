# LocalGuardian

**Voice-Driven Local LLM Agent for Sandboxed Windows OS and Browser Automation (`v0.2.0`)**

LocalGuardian lets you control Windows (brightness, volume, media playback, window snapping, sandboxed screenshots, workspace presets, allowlisted apps) and **Google Chrome** (#1 priority browser) using natural voice or text commands—powered by a **3-tier 100% local cascade**:

1. **Tier 1 — Fast Grammar (CPU, <1 ms):** Instant deterministic matching for direct commands.
2. **Tier 1.5 — Cactus Needle 3 (CPU, ~70–130 ms, ~131 MB RAM, 0 VRAM):** Confidence-gated on-device tool router (`cactus-compute`) that handles casual single-step phrasing without waking the GPU LLM.
3. **Tier 2 — Ollama `qwen3:4b` (RTX 4050 GPU, ~3 GB VRAM):** Multi-step natural language reasoning & native tool calling whenever Tier 1.5 confidence is below threshold (`0.65`) or multiple tools are needed.

Every tool call passes through a **hard-coded Python safety sandbox** that can never touch `C:\Windows`, `C:\Program Files`, Registry, credentials, or raw PowerShell.

---

## Tech Stack & Local Models Used (v0.2.0)

| Layer | Technology / Model | Purpose |
| :--- | :--- | :--- |
| **Language & Environment** | Python 3.11 + Anaconda (`localguardian` env) | Clean Windows dependency isolation (`pyproject.toml` + `environment.yml`) |
| **Voice Input (CPU, 0 VRAM)** | `sounddevice` + `numpy` + **`faster-whisper`** (`base.en`, `int8`) **or `Cactus Whistle`** (16.9 MB) | Dual offline CPU speech-to-text backends (`--stt whisper` or `--stt whistle`)—keeps 100% of GPU VRAM free for Qwen3 |
| **Tier 1 — Fast Router (CPU)** | Pure Python Deterministic Fast Grammar (`fast_grammar.py`) | <1 ms execution for direct commands & explicit adversarial safety catches |
| **Tier 1.5 — Edge Tool Router (CPU)** | **`cactus-compute` (`cactus.Needle`)** (`min_confidence=0.65`, `CACTUS_TELEMETRY=0`) | ~70–130 ms on-device grounded tool calling (~131 MB RAM); cleanly escalates uncertain or multi-step prompts to Tier 2 |
| **Tier 2 — Local LLM (GPU)** | **Ollama** (`http://127.0.0.1:11434/v1`) + **`qwen3:4b`** (`Q4_K_M`, GGUF, ~3 GB VRAM) via `httpx` | Multi-step reasoning & native tool calling with `<think>` stripping and JSON repair (tested on RTX 4050 6 GB VRAM) |
| **Browser Automation (#1)** | **Playwright (`channel="chrome"`)** + native Chrome fallback | Drives installed **Google Chrome** first via semantic DOM locators (Edge/Chromium only if Chrome is absent) |
| **Windows OS & Window Controls** | `screen-brightness-control`, `pycaw`, `pywin32`, `psutil`, `Pillow`, `ctypes` | Typed native brightness, volume/mute, media keys, window list/focus/left-right snapping, sandboxed PNG screenshots, workspace presets, and read-only CPU/RAM/GPU/battery diagnostics |
| **Tool Protocol (MCP)** | Official **`mcp` Python SDK** (`MCPServer` on `mcp 2.x`, `FastMCP` v1 fallback) | Exposes all 17 safety-gated Windows & Chrome tools over `stdio` for external MCP clients |
| **Safety, Validation & Audit** | **Pydantic v2**, `PyYAML`, `sqlite3`, `Tkinter` | Hard-coded OS/Program Files/Registry/secret/hotkey/URL/screenshot-traversal blocks, strict schemas, confirmation modal, emergency failsafe, and local SQLite audit log |
| **Testing** | `pytest` + `pytest-asyncio` | Automated test suite covering adversarial safety attacks, Cactus Needle confidence gating, window/media/screenshot tools, LLM JSON repair, MCP, and end-to-end orchestration |

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

### Step 3: Install LocalGuardian, Cactus Needle/Whistle & Dependencies
Inside the activated `localguardian` environment:
```powershell
pip install -e ".[cactus,browser,mcp,dev]" faster-whisper sounddevice numpy
```

### Step 4: Install Ollama & Pull the Local LLM (`qwen3:4b`)
*(Needed for Tier-2 multi-step reasoning; Tier-1 grammar and Tier-1.5 Cactus Needle already work on CPU without Ollama.)*
```powershell
winget install -e --id Ollama.Ollama
```
Start Ollama (launch **Ollama** from the Windows Start Menu, or run `ollama serve` in a separate terminal), then pull the model:
```powershell
ollama pull qwen3:4b
```

### Step 5: Verify All 3 Tiers, Cactus Needle, Safety Guardrails & Models
From **regular PowerShell** (works even if `conda` is not on your `PATH`):
```powershell
.\run.ps1 --doctor
.\run.ps1 --models
```
*(Or in **Anaconda Prompt** after `conda activate localguardian`: `localguardian --doctor` and `localguardian --models`.)*

### Step 6: Run LocalGuardian

**Live push-to-talk local voice mode (default `faster-whisper` on CPU):**
```powershell
.\run.ps1 --voice
```

**Ultra-light voice mode using Cactus Whistle (16.9 MB CPU STT):**
```powershell
.\run.ps1 --voice --stt whistle
```

**Live interactive text mode (shows which tier handled every command):**
```powershell
.\run.ps1 --text
```

**Safe dry-run simulation (no real OS or Chrome changes):**
```powershell
.\run.ps1 --text --dry-run
.\run.ps1 --voice --dry-run
```

**Single one-shot commands:**
```powershell
.\run.ps1 --once "Windows, increase the brightness"
.\run.ps1 --once "put volume to 40"
.\run.ps1 --once "go to Chrome and type Elon Musk"
.\run.ps1 --once "put chrome on the left"
.\run.ps1 --once "check system status"
```

*(Optional: add `--no-needle` to any command to skip Tier-1.5 Cactus Needle and compare directly against Tier-2 Ollama.)*

### Step 7: Inspect Audit Logs, Run Tests, or Start MCP Server
```powershell
# View every executed and blocked command logged to ~/.localguardian/audit.db
.\run.ps1 --audit

# Run the full automated test suite (including adversarial safety & Needle tests)
& "$env:USERPROFILE\anaconda3\envs\localguardian\python.exe" -m pytest -v

# Expose LocalGuardian's sandboxed tools as an MCP stdio server
.\run.ps1 --mcp
```

---

## Example Commands to Try

- **Tier 1 — Fast Grammar (<1 ms CPU):**
  - `Windows, increase the brightness` / `set brightness to 70`
  - `increase volume` / `decrease volume by 15` / `mute` / `unmute`
  - `pause music` / `next track` / `previous song`
  - `go to Chrome and type Elon Musk` / `open github.com in chrome`
  - `list open windows` / `put chrome on the left` / `maximize chrome` / `focus notepad`
  - `take a screenshot` / `switch to study mode` / `coding mode`
  - `check system status` *(live brightness, volume, battery, CPU, RAM, RTX 4050 GPU temp & VRAM)*
- **Tier 1.5 — Cactus Needle 3 (~70–130 ms CPU):**
  - `put volume to 40`
  - `open website github.com`
  - `can you open notepad`
- **Tier 2 — Ollama `qwen3:4b` (GPU Multi-Step):**
  - `my eyes hurt, lower brightness a bit and also look up SpaceX in Chrome`
- **Safety Guardrail Tests (Hard-Blocked + Audited):**
  - `delete C:\Windows\System32`
  - `modify C:\Program Files`
  - `run powershell`
  - `take screenshot named ..\..\Windows\evil.png`
  - `open file:///C:/Windows/win.ini in chrome`

---

## Documentation

- [PROTOTYPE.md](./PROTOTYPE.md) — Exact breakdown of what is built in v0.2 and why each library/model was chosen.
- [FLOWCHART_RESEARCH.md](./FLOWCHART_RESEARCH.md) — End-to-end architecture, safety decision tree, and sequence flowcharts.
- [RESEARCH.md](./RESEARCH.md) — Full research blueprint, SOTA model comparisons, hardware profiles, and roadmap.

## Core Safety Guarantees

- Runs as a **standard non-admin user** (never requests UAC elevation).
- **Zero raw PowerShell/cmd execution**—neither Cactus Needle nor Qwen3 ever sees a shell tool.
- Hard-coded blocks on `C:\Windows`, `C:\Program Files`, `C:\Program Files (x86)`, `C:\ProgramData`, `AppData`, Windows Registry, credential stores, screenshot path escapes, unsafe URL schemes (`file://`, `chrome://`, `javascript:`), and OS hotkeys (`Win+*`, `Alt+F4`, `Ctrl+Alt+Del`).
- Every command and policy decision is logged locally to `~/.localguardian/audit.db` (`.\run.ps1 --audit`).

## License

MIT — see [LICENSE](./LICENSE).
