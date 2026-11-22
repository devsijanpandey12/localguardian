# LocalGuardian — Research Blueprint & Technical Specification

> **Project Name:** **LocalGuardian**  
> **Formal Project Title:** *Voice-Driven Local LLM Agent for Sandboxed Windows OS and Browser Automation*  
> **Design Reference Analyzed (Inspiration Only — Not Directly Integrated):** [`ashimst/servo`](https://github.com/ashimst/servo)  
> **Target Platform:** Windows 10 / 11 (64-bit), 100% Local-First Execution  
> **Conda Environment:** `localguardian` (Python 3.11)

---

## 1. Project Identity & Formal Title Options

If you present this as an open-source repository, portfolio project, or academic/capstone topic, here are clean, descriptive titles paired with the **LocalGuardian** name:

| Use Case | Recommended Title |
| :--- | :--- |
| **Open-Source Repo / Portfolio** | **LocalGuardian** — *Voice-Driven Local LLM Agent for Sandboxed Windows OS & Browser Automation* |
| **Academic / Capstone Topic** | *LocalGuardian: A Safety-Gated, On-Device Voice Automation Agent for Windows Using Lightweight Tool-Calling Models* |
| **Research-Focused Framing** | *Neuro-Symbolic On-Device Desktop Control: Combining Local Tool-Calling Models, Windows UI Automation, and Deterministic Safety Sandboxing* |

### Core Goal
Speak natural commands to your Windows PC — such as:
- *"Windows, increase the brightness"*
- *"Lower the volume to 40 percent"*
- *"Go to Chrome and search Elon Musk"*

Everything runs **locally on your machine** (voice recognition, intent routing, LLM reasoning, and Windows/browser execution) behind **strict code-enforced safety boundaries** so system files (`C:\Windows`, `C:\Program Files`, Registry, credentials) can never be touched or corrupted.

---

## 2. Design Reference Analysis: `ashimst/servo`

> **Note:** `ashimst/servo` is studied strictly as an **architectural reference** — we are building **LocalGuardian** cleanly from scratch with our own streamlined, voice-first, hard-sandboxed design.

### What Makes Servo's Architecture Worth Studying
Servo (`v0.2.0`, Python 3.10–3.12) avoids the classic slow/fragile "send a screenshot to a giant VLM for every click" loop by using a **three-tier Cognitive Cascade**:

```text
Voice / Text Input
       │
       ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Tier 1: Fast Reflex & Intent Parsing (On-Device CPU, <200 ms)        │
│  • Deterministic command grammar (`needle.py`)                       │
│  • Cactus Needle 3 (`cactus.Needle`) for single-step tool calls      │
└──────────────┬───────────────────────────────────────┬───────────────┘
               │ Single confident command              │ Multi-step / complex / low confidence
               ▼                                       ▼
┌──────────────────────────────┐     ┌─────────────────────────────────┐
│ Independent Safety Gate      │ ◄── │ Tier 2: Local LLM Planner       │
│  • Risk tier (low/med/high)  │     │  • Ollama / OpenAI-compatible   │
│  • Hard policy floor         │     │  • Decomposes goal into atomic  │
│  • User confirmation prompt  │     │    typed tool steps             │
└──────────────┬───────────────┘     └─────────────────────────────────┘
               │ Approved
               ▼
┌──────────────────────────────────────────────────────────────────────┐
│ Tier 3: Perception & Sandboxed Actuation                             │
│  • Native OS APIs (brightness, volume, allowlisted apps)             │
│  • Browser DOM via Playwright (Chrome/Edge)                          │
│  • Desktop UI Tree via Windows UI Automation (`pywinauto`)           │
│  • Vision Fallback ONLY if UIA/DOM misses (Mirage / OmniParser)      │
└──────────────────────────────────────────────────────────────────────┘
```

### Key Architectural Takeaways from Servo
1. **Separate perception misses from reasoning misses:** If a button isn't in Windows UIA, fall back sideways to vision — don't waste an LLM call. Only escalate to the larger local LLM when a command actually requires multi-step planning.
2. **Use accessibility trees & browser DOM before pixels:** Windows UIA (`pywinauto`) and Playwright DOM locators are 10× faster and far more reliable than guessing `(x, y)` coordinates from screenshots.
3. **Never trust small local models' raw JSON blindly:** Servo uses a multi-stage JSON repair pipeline (stripping markdown fences, fixing trailing commas/quotes, normalizing schemas) so 4B–8B local models don't crash on minor formatting errors.
4. **Enforce safety outside the LLM:** Servo combines a non-autoregressive decision model (**Kev**) with a deterministic code-level risk floor, window bounds checks, hotkey blacklists, and confirmation dialogs.
5. **Where LocalGuardian Improves on Servo for Your Goal:**
   - **No open shell tool by default:** Instead of exposing arbitrary PowerShell, LocalGuardian uses **narrow, typed native Windows tools** (WMI/DDC-CI brightness, Core Audio volume, allowlisted app launcher).
   - **Always-ready voice pipeline:** Adds `openWakeWord` + `Silero VAD` for true hands-free *"Windows, ..."* / wake-word activation (Servo only transcribes recorded clips).
   - **Hard OS/Program Files isolation:** Default-deny file allowlist so `C:\Windows`, `C:\Program Files`, and Registry are unreachable by design.

---

## 3. Cactus Compute Models (`Needle`, `Whistle`, `Mirage`)

**Cactus Compute** (`pip install cactus-compute`, [github.com/cactus-compute/cactus](https://github.com/cactus-compute/cactus)) builds ultra-compact, open-weight on-device models (using specialized architectures and aggressive quantization down to 2-bit) powered by a C++ FFI runtime:

| Model | Footprint | Purpose | Role in LocalGuardian |
| :--- | :--- | :--- | :--- |
| **Needle (Needle 3)** | ~8–35 MB (29M–121M params) | **On-device tool calling & parameter extraction.** Maps a spoken command + JSON tool schemas directly into structured function calls with a calibrated `confidence` score. | **Optional Tier-1 fast router** on CPU: executes *"increase brightness"* in milliseconds without waking the GPU LLM. |
| **Whistle** | ~16.9 MB | **Ultra-light offline Speech-to-Text** (7 languages, word timestamps, CPU-friendly). | Lightweight fallback/alternative to `faster-whisper` on low-RAM laptops. |
| **Mirage** | ~22 MB (~51.3M params) | **Edge Vision-Language Model** (single-pass OCR + object detection + bounding boxes, <100 ms target). | Optional vision fallback when Windows UIA cannot read a custom UI element. |

> **Practical Caveat:** Needle is built strictly for **single-step tool extraction**, not multi-step reasoning. Complex instructions still escalate to a 4B–8B local LLM via Ollama. Also note: `cactus-compute` and `cactus-engine` both use the `cactus` module name and cannot be installed in the same Conda environment.

---

## 4. Best Local Models for Your Hardware & Open-Source Users

### 4.1 Your Machine's Measured Hardware Profile
- **CPU:** AMD Ryzen 7 7840HS (8 cores / 16 threads)
- **System RAM:** 16 GB (15.2 GB usable)
- **GPU:** NVIDIA GeForce RTX 4050 Laptop GPU — **6 GB VRAM** (6,141 MiB)

### 4.2 The Best Model Stack for Your Machine (Recommended)

Because your RTX 4050 has **6 GB VRAM** and your Ryzen 7 7840HS CPU is very fast, the optimal strategy is a **CPU + GPU split**: run Voice (wake word + VAD + STT) and Tier-1 routing on CPU so **100% of your 6 GB VRAM stays dedicated to your local LLM**:

| Layer | Best Choice for Your PC | Compute | Footprint | Why It's the Best Fit |
| :--- | :--- | :--- | :--- | :--- |
| **Wake Word** | **`openWakeWord`** (ONNX) | CPU | ~20 MB RAM | Always-on, <2% CPU, supports custom wake phrases completely offline. |
| **Speech End Detection** | **`Silero VAD`** | CPU | ~2 MB RAM | Cleanly detects when you finish speaking so latency stays low. |
| **Speech-to-Text (STT)** | **`faster-whisper` (`small.en` or `base.en`, `int8`)** *(or Cactus Whistle)* | **CPU** (Ryzen 7) | ~250–500 MB RAM | Sub-second English transcription on 8-core Ryzen while keeping **0 MB VRAM** used on your RTX 4050. |
| **Tier-1 Fast Router** | **Deterministic Grammar + Cactus Needle 3** | **CPU** | ~35 MB RAM | Handles instant OS commands (*brightness, volume, open Chrome*) in <100 ms with zero LLM wait. |
| **Tier-2 Primary LLM (Best Overall)** | **`qwen3:4b`** *(fastest)* **or `qwen3:8b` / `qwen2.5:7b`** *(smartest)* via **Ollama** | **GPU** (RTX 4050) | 2.6 GB (`4b`) / 4.7–5.2 GB (`7b/8b`) VRAM | **Qwen3 / Qwen2.5** are the current gold standard for local function calling & strict JSON tool use. `qwen3:4b` gives blazing-fast responses with ~3 GB VRAM headroom; `qwen2.5:7b` or `qwen3:8b` (Q4_K_M) gives stronger multi-step reasoning while still fitting inside 6 GB VRAM when STT is on CPU. |
| **Tier-3 Vision Fallback (Optional)** | **`Cactus Mirage`** *(CPU)* or **`Microsoft OmniParser`** / **`qwen2.5vl:3b`** *(on-demand)* | CPU / GPU | 22 MB / ~3.2 GB | Only loaded when Windows UIA / Playwright DOM cannot find a visual target. |

### 4.3 Model Selection Guide for Open-Source Users (Auto-Profiled by Hardware)

When you open-source **LocalGuardian**, users will have different PCs. Ship three hardware profiles in config:

| Profile | Target Hardware | STT | Tier-2 Local LLM (Ollama) | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **`lite` (CPU-only)** | No dGPU, 8–16 GB RAM | `faster-whisper tiny.en` or `Cactus Whistle` | `qwen3:1.7b` or `qwen3:4b` (+ Cactus Needle 3) | Fully usable on standard laptops. |
| **`balanced` (Default — Your PC)** | 6–8 GB VRAM + 16 GB RAM | `faster-whisper base.en` / `small.en` (CPU `int8`) | **`qwen3:4b`** (snappy) or **`qwen3:8b` / `qwen2.5:7b`** (high accuracy) | Best balance of speed & multi-step reliability. |
| **`pro` (High VRAM)** | 12–24 GB VRAM + 32 GB RAM | `faster-whisper small.en` (CUDA `float16`) | **`qwen3:14b`** or **`gemma4:12b`** + **UI-TARS / Qwen-VL** | Near-cloud agent reliability + vision GUI control. |

---

## 5. Current State-of-the-Art Open-Source Tools (2025–2026)

| Category | SOTA Open-Source Tools | Role in LocalGuardian |
| :--- | :--- | :--- |
| **Local LLM Serving** | **Ollama**, LM Studio, `llama.cpp` | Serves Qwen3 / Gemma 4 over local OpenAI-compatible API (`http://127.0.0.1:11434/v1`) with native tool calling. |
| **Voice Stack** | **`openWakeWord`**, **`Silero VAD`**, **`faster-whisper`**, **Cactus Whistle**, *Moonshine / Parakeet* | Fully offline wake-word → VAD → fast transcription. |
| **Native Windows OS Controls** | **`screen-brightness-control`** (WMI + DDC/CI), **`pycaw`** (Windows Core Audio), **`pywin32`** | Safe, typed Python APIs for brightness, volume, mute, media, and window management — **zero shell injection risk**. |
| **Browser Automation** | **Playwright — Google Chrome Priority #1** (`channel="chrome"`, Edge/Chromium fallback only if Chrome is missing) | First-priority browser engine for *"go to Chrome and search Elon Musk"*, opening URLs, filling forms, and clicking links via DOM locators. |
| **Desktop Accessibility** | **`pywinauto`** (UIA backend), **Microsoft UFO** dual-agent pattern | Inspects Windows Accessibility Tree (UIA) to click named buttons/inputs cleanly across native Win32/UWP apps. |
| **Visual GUI Grounding** | **Microsoft OmniParser**, **ByteDance UI-TARS**, **Cactus Mirage** | Fallback screen parsing for custom apps/canvases lacking UIA trees. |
| **Tool Interoperability (MCP)** | **`mcp` Python SDK / `fastmcp`** (`pip install mcp` or `pip install fastmcp`) | Protocol + Python library that wraps our typed, safety-gated Windows/Chrome functions with `@mcp.tool()` so any local LLM or external MCP client can invoke them safely. |
| **Learned Safety Gate (Optional)** | **Kev** (`jaredpalmer/kev`, open TypeSafe Jev decision model) | Optional non-autoregressive probabilistic risk classifier layered on top of deterministic Python rules. |

---

## 6. Safeguards & System Protection Architecture (Non-Negotiable)

> **Golden Rule:** *Safety is enforced by deterministic Python code and Windows OS permissions — NEVER solely by LLM prompts.* Even if a local model hallucinates or reads a malicious webpage (prompt injection), the action engine will refuse unsafe calls before touching Windows.

### 6.1 Hard Boundaries: Protecting System & Program Files

1. **Standard User Privilege Only (Never Run as Administrator):**
   - LocalGuardian **must never request UAC elevation**. It runs as a standard Windows user process.
   - Windows **NTFS ACLs** and **UIPI (User Interface Privilege Isolation)** enforce kernel-level walls: LocalGuardian physically cannot modify `C:\Windows`, `C:\Program Files`, or inject clicks/keys into UAC prompts, Task Manager, or elevated installers.
2. **Code-Level Protected Path Denylist + Default-Deny File Allowlist:**
   - Every file path is canonicalized via `Path(raw).resolve(strict=False)` (defeating `..\..\Windows` traversal and symlink escapes).
   - **Hard-Blocked Paths (Zero Read/Write/Delete/Execute):**
     - `C:\Windows\**` (`%SystemRoot%`, `%WINDIR%`)
     - `C:\Program Files\**` and `C:\Program Files (x86)\**`
     - `C:\ProgramData\**`
     - `C:\Users\<user>\AppData\**` (blocks Startup folder persistence, browser cookies/passwords, Windows Credentials)
     - Windows Registry (`HKLM`, `HKCU\...\Run`)
     - Credential files & folders (`.ssh`, `.aws`, `.env`, `.pem`, `.key`, `.kdbx`) and LocalGuardian's own config folder (`~/.localguardian`).
   - **Default-Deny Allowlist for User Files:** File tools (if enabled) can *only* access explicitly opted-in folders (e.g., `Desktop`, `Documents`, `Downloads`, or `~/LocalGuardian_Workspace`).
3. **Zero Raw Shell Access (Typed Tools Only):**
   - **Do NOT give the LLM a `run_powershell` or `run_cmd` tool.**
   - Every OS capability is a narrow, strictly validated Python function:
     - `set_brightness(level)` / `adjust_brightness(delta)` → clamped `0..100`, calls `screen-brightness-control`.
     - `set_volume(level)` / `adjust_volume(delta)` / `toggle_mute()` → clamped `0..100`, calls `pycaw`.
     - `open_app(app_key)` → resolves *only* against a user-editable **application allowlist** (`chrome`, `edge`, `notepad`, `calculator`, `spotify`, etc.) — never runs arbitrary `.exe`/`.bat`/`.ps1` paths.
     - `browser_search(query)` / `browser_open_url(url)` → allows `http://` and `https://` only (blocks `file://`, `chrome://settings`, `javascript:`).

### 6.2 Runtime Execution Guardrails

| Guardrail | Implementation | Protection Provided |
| :--- | :--- | :--- |
| **4-Level Action Risk Gate** | • **`SAFE` (Auto-run):** brightness, volume, media play/pause, open allowlisted app, web search.<br>• **`MEDIUM` (Confirm Popup / Voice "Yes"):** writing a file in allowlisted user folder, filling/submitting web forms, closing a window.<br>• **`HIGH` (Explicit Visual Click Confirm):** overwriting user files, downloading files.<br>• **`FORBIDDEN` (Always Blocked):** touching system/program files, Registry, shell commands, deleting outside workspace, installing/uninstalling software. | Stops both model hallucinations and misheard voice commands. |
| **Hotkey Blacklist** | Deterministically block `Win+*`, `Win+R`, `Alt+F4`, `Ctrl+Alt+Del`, `Ctrl+Shift+Esc`. | Prevents GUI actuation from opening Run dialogs or killing apps. |
| **Window Focus & Bounds Check** | Confirm target `HWND` is foreground and unoccluded (`WindowFromPoint`) and target point lies strictly inside its client rectangle before clicking/typing. | Prevents sending text/clicks into a surprise popup or password field. |
| **Emergency Kill Switch** | Global hotkey (`Ctrl+Shift+Esc` alternative like `Ctrl+Alt+X` or double-`Esc`) + mouse-to-top-left-corner slam immediately halts all actions. | Instant manual override at any millisecond. |
| **Dry-Run Mode & Audit Trail** | `--dry-run` logs intended tool calls without touching OS/GUI; SQLite log (`~/.localguardian/audit.db`) records every transcript, model output, policy decision, and action. | Safe testing and full transparency. |

---

## 7. Proposed Project Architecture (`LocalGuardian`)

```text
localguardian/
├── pyproject.toml                 # Modern Python packaging & CLI entry point (`localguardian`)
├── environment.yml                # Reproducible Conda environment spec for contributors
├── LICENSE                        # MIT License
├── README.md                      # User-facing quickstart & safety guarantee overview
├── SECURITY.md                    # Responsible disclosure & sandbox threat model
├── config/
│   ├── default_config.yaml        # Hardware profiles (lite/balanced/pro), allowed apps, wake word
│   └── safety_policy.yaml         # Allowlisted user folders, risk rules (protected paths stay hard-coded!)
├── src/localguardian/
│   ├── cli.py                     # CLI entry: `localguardian`, `--dry-run`, `--text`, `--doctor`, `--mcp`
│   ├── mcp_server.py              # Optional FastMCP (`mcp` SDK) server exposing all safety-gated tools
│   ├── voice/
│   │   ├── listener.py            # openWakeWord + Silero VAD + mic capture
│   │   └── stt.py                 # faster-whisper (CPU int8) + optional Cactus Whistle
│   ├── brain/
│   │   ├── fast_grammar.py        # Instant deterministic parser (brightness, volume, open Chrome/apps)
│   │   ├── needle_router.py       # Optional Cactus Needle 3 Tier-1 tool router
│   │   ├── llm_planner.py         # Ollama OpenAI-compat client (Qwen3 / Qwen2.5) + JSON repair
│   │   └── orchestrator.py        # Cascade controller: Fast Grammar -> Needle -> Ollama -> Tools
│   ├── safety/
│   │   ├── policy.py              # Hard-coded OS/Program Files denylist, path resolver, risk engine
│   │   ├── confirm.py             # Desktop confirmation dialog (Tkinter/PyWebView)
│   │   ├── failsafe.py            # Global kill-switch & window focus/bounds verifier
│   │   └── audit.py               # Local SQLite trace & action log
│   ├── tools/
│   │   ├── registry.py            # Typed Pydantic tool schemas & dispatcher
│   │   ├── os_controls.py         # Brightness (`screen-brightness-control`), volume (`pycaw`), apps
│   │   ├── browser.py             # Playwright Google Chrome #1 priority controller (Edge fallback only if absent)
│   │   └── desktop_uia.py         # Windows UIA (`pywinauto`) control tree & sandboxed input
│   └── ui/
│       └── tray.py                # Minimal Windows system tray / floating HUD status indicator
└── tests/
    ├── test_safety_policy.py      # Adversarial tests: C:\Windows, Program Files, traversal, hotkeys
    ├── test_fast_grammar.py       # Deterministic command parsing tests
    ├── test_llm_planner.py        # Mocked tool-calling & malformed JSON repair tests
    └── test_tools_dry_run.py      # End-to-end pipeline verification without moving mouse
```

---

## 8. How to Run It & Open-Source User Guide

This section outlines **both** how you will develop/run **LocalGuardian** locally and how external users will install and run it smoothly if you release it as an open-source project on GitHub.

### 8.1 Developer Setup (Your Machine — Conda)

```powershell
# 1. Activate the dedicated Conda environment (Python 3.11)
conda activate localguardian

# 2. Install LocalGuardian in editable mode with dev tools
pip install -e ".[dev]"

# 3. Install Ollama (one-time Windows install) and pull the recommended local model
winget install Ollama.Ollama
ollama pull qwen3:4b        # Snappy default for 6 GB VRAM (or `ollama pull qwen3:8b`)

# 4. Run system & safety self-check (verifies mic, Ollama, Playwright, and safety blocks)
localguardian --doctor

# 5. Start in safe Dry-Run mode first (prints planned actions without executing)
localguardian --dry-run

# 6. Run live voice assistant (or text-only testing mode)
localguardian               # Hands-free voice mode + system tray icon
localguardian --text        # Interactive terminal prompt mode (no mic needed)
```

### 8.2 End-User Experience for an Open-Source Release

For non-developer Windows users to try your open-source release without friction, design around **3 installation tiers**:

1. **Standard Python / `uv` / `pip` Install (Developers & Power Users):**
   ```powershell
   pip install localguardian
   localguardian setup    # Guided wizard: checks GPU/RAM, installs Ollama model, tests mic
   localguardian          # Launches tray app + floating status bar
   ```
2. **One-Command Windows Bootstrapper (`install.ps1`):**
   - Checks Windows 10/11 + Python/Conda.
   - Detects GPU VRAM automatically (`nvidia-smi`) and recommends `lite`, `balanced`, or `pro` profile.
   - Checks if Ollama is installed and offers to pull the matching Qwen model.
   - Creates a Desktop / Start Menu shortcut that runs `localguardian` as a **non-elevated standard user**.
3. **Standalone Packaged Release (Future Milestone — GitHub Releases):**
   - Bundle with **PyInstaller / Nuitka** + Inno Setup installer (`LocalGuardian-Setup.exe`) so everyday Windows users can double-click and run without installing Python or Conda manually.

### 8.3 Essential Open-Source Release Checklist
- [ ] **`localguardian --doctor` command:** Diagnoses microphone permissions, Ollama connection, Chrome/Edge availability, GPU VRAM, and verifies safety guardrails are active.
- [ ] **First-Run Onboarding & Permission Summary:** Clearly shows the user which apps/folders are allowlisted, what is hard-blocked (`C:\Windows`, `Program Files`), and what the kill-switch hotkey is.
- [ ] **Clean `README.md` with Architecture Diagram + Demo GIF:** Show *"Windows, increase brightness"* and *"Go to Chrome and search Elon Musk"* running completely offline (Wi-Fi disabled for OS commands).
- [ ] **`SECURITY.md` + Adversarial Safety Test Suite:** Publish automated tests proving protected paths, shell injection, and prompt injection attempts fail closed.
- [ ] **MIT or Apache-2.0 License** + `.gitignore` ensuring no local logs, audio recordings, or user configs are ever committed.

---

## 9. Phased Implementation Plan (Ready After Your Review)

Once you review and approve this blueprint, we will build **LocalGuardian** step by step:

1. **Phase 1 — Project Scaffold & Safety Core First:**
   - Initialize `pyproject.toml`, `src/localguardian/`, hard-coded `safety/policy.py`, `failsafe.py`, `audit.py`, and adversarial `pytest` safety suite (proving system/program files cannot be touched).
2. **Phase 2 — Typed Windows OS & Chrome Tools:**
   - Implement `os_controls.py` (brightness, volume, allowlisted apps) and `browser.py` (Playwright Chrome navigation & search), verifiable via `--text` and `--dry-run`.
3. **Phase 3 — Local Brain Cascade (Fast Grammar + Ollama Qwen3 + Optional Cactus Needle):**
   - Implement deterministic fast path, Ollama local tool-calling client with JSON repair, and risk confirmation prompts.
4. **Phase 4 — Local Voice Pipeline (`openWakeWord` + `Silero VAD` + `faster-whisper`):**
   - Wire hands-free microphone listening, end-of-speech detection, offline transcription, and spoken/visual feedback.
5. **Phase 5 — Windows UI Automation (`pywinauto`), System Tray UI & Open-Source Packaging:**
   - Add general Windows UIA element interaction, minimal floating status/confirmation overlay, `localguardian --doctor`, `README.md`, and `SECURITY.md`.

---

## 10. Key References

- **Servo (Architectural Inspiration):** https://github.com/ashimst/servo
- **Cactus Compute (Needle 3, Whistle, Mirage):** https://github.com/cactus-compute/cactus
- **Kev (Open-Source Decision Model / Safety Gate):** https://github.com/jaredpalmer/kev
- **Microsoft UFO (Windows UIA Dual-Agent):** https://github.com/microsoft/UFO
- **Microsoft OmniParser (GUI Screen Parser):** https://github.com/microsoft/OmniParser
- **UI-TARS Desktop (ByteDance Open GUI Agent):** https://github.com/bytedance/UI-TARS-desktop
- **Ollama (Local LLM Server):** https://ollama.com
- **faster-whisper (Offline STT):** https://github.com/SYSTRAN/faster-whisper
- **openWakeWord (Offline Wake Word):** https://github.com/dscripka/openWakeWord
- **screen-brightness-control (Windows WMI / DDC-CI):** https://github.com/Crozzers/screen_brightness_control
