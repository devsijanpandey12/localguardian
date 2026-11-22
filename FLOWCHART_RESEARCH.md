# LocalGuardian — Complete System Architecture & Flowcharts

> **Project:** LocalGuardian (*Voice-Driven Local LLM Agent for Sandboxed Windows OS and Browser Automation*)  
> **Companion Blueprint:** [RESEARCH.md](./RESEARCH.md)

This document maps out everything happening inside **LocalGuardian** from the moment you speak a command to the moment Windows or Google Chrome safely executes it.

---

## 1. End-to-End System Architecture Flowchart

```mermaid
flowchart TD
    %% 1. Input Layer
    subgraph INPUT["1. Input Layer (CPU - Zero GPU VRAM)"]
        MIC["Microphone Stream (16 kHz)"] --> TRIGGER{"Trigger Mode"}
        TRIGGER -->|"Hands-Free"| OWW["openWakeWord (ONNX)"]
        TRIGGER -->|"Push-to-Talk"| PTT["Global Hotkey"]
        OWW --> VAD["Silero VAD (End-of-Speech)"]
        PTT --> VAD
        VAD --> STT["faster-whisper base.en int8 / Cactus Whistle"]
        CLI["CLI --text Mode"] --> TEXT["Normalized Command Text"]
        STT --> TEXT
    end

    %% 2. Local Brain Cascade
    subgraph BRAIN["2. Local Cognitive Cascade"]
        TEXT --> TIER1["Tier 1: Deterministic Fast Grammar (CPU)"]
        TIER1 -->|"Exact match (brightness, volume, open Chrome)"| PLAN["Typed Tool Call(s)"]
        TIER1 -->|"No exact match"| NEEDLE{"Optional: Cactus Needle 3 (CPU)"}
        NEEDLE -->|"Confidence >= 0.70 (Single Step)"| PLAN
        NEEDLE -->|"Low confidence or Multi-step"| TIER2["Tier 2: Ollama Local LLM (qwen3:4b on RTX 4050 GPU)"]
        TIER2 --> REPAIR["Multi-Stage JSON Repair & Pydantic Schema Validator"]
        REPAIR --> PLAN
    end

    %% 3. Independent Safety Gate
    subgraph SAFETY["3. Hard-Coded Safety Policy Gate (Non-LLM Python Code)"]
        PLAN --> POLICY["safety/policy.py (Protected Paths, App/URL Allowlists, Hotkey Blacklist)"]
        POLICY --> RISK{"Risk Classification"}
        RISK -->|"FORBIDDEN (C:/Windows, Program Files, Shell, Registry)"| BLOCK["Hard Block + Explain Refusal"]
        RISK -->|"SAFE (Brightness, Volume, Allowlisted App, Chrome Search)"| DRY{"--dry-run Mode?"}
        RISK -->|"MEDIUM / HIGH (Write User File, Submit Form, Close App)"| CONFIRM["Tkinter Visual Confirmation Popup"]
        CONFIRM -->|"User Denies / Timeout"| BLOCK
        CONFIRM -->|"User Approves"| DRY
    end

    %% 4. Execution Layer
    subgraph TOOLS["4. Sandboxed Execution Layer (Also Exposed via MCP)"]
        DRY -->|"Yes"| SIM["Log Simulated Action Only"]
        DRY -->|"No"| DISPATCH["Typed Tool Registry / FastMCP Server"]
        DISPATCH --> OS["OS Controls (screen-brightness-control, pycaw, Allowlisted Apps)"]
        DISPATCH --> CHROME["Browser #1 Priority: Google Chrome (Playwright channel=chrome)"]
        DISPATCH --> UIA["Desktop UIA (pywinauto + Window Bounds & Focus Check)"]
        UIA -.->|"UIA Miss Only"| VISION["Optional Vision Fallback (Cactus Mirage / OmniParser)"]
    end

    %% 5. Observability & Override
    subgraph OBSERVE["5. Audit, Feedback & Failsafe"]
        OS --> RESULT["Execution Result"]
        CHROME --> RESULT
        UIA --> RESULT
        SIM --> RESULT
        BLOCK --> RESULT
        RESULT --> AUDIT["SQLite Audit Log (~/.localguardian/audit.db)"]
        RESULT --> UI["Tray / Console Status & Spoken Feedback"]
        KILL["Emergency Kill Switch (Global Hotkey / Corner Slam)"] -.->|"Instant Abort"| DISPATCH
    end
```

---

## 2. Hard Safety & Sandboxing Decision Flow

Safety is enforced purely in deterministic Python code and Windows OS permissions (**never** relying on LLM prompt obedience).

```mermaid
flowchart TD
    CALL["Incoming Tool Call (tool_name, args)"] --> PRIV["Check Process Privilege (Must Be Non-Admin Standard User)"]
    PRIV --> EXISTS{"Is tool_name in Typed Tool Registry?"}
    EXISTS -->|"No (e.g. raw PowerShell / cmd)"| DENY1["BLOCK: Tool Does Not Exist"]
    EXISTS -->|"Yes"| ARGS["Validate Arguments with Strict Pydantic Schema"]
    ARGS -->|"Invalid types / out of bounds"| DENY2["BLOCK: Schema Validation Failed"]
    ARGS -->|"Valid"| PATHCHECK{"Touches Filesystem, App, URL, or Hotkey?"}

    PATHCHECK -->|"File Path"| CANON["Resolve Canonical Path (No .. traversal or symlinks)"]
    CANON --> DENYLIST{"Inside C:/Windows, Program Files, ProgramData, AppData, Registry, or Secrets?"}
    DENYLIST -->|"Yes"| DENY3["FORBIDDEN: Protected System or Secret Path"]
    DENYLIST -->|"No"| ALLOWDIR{"Inside User-Approved Allowlist Folder?"}
    ALLOWDIR -->|"No"| DENY4["FORBIDDEN: Outside Default-Deny Allowlist"]
    ALLOWDIR -->|"Yes"| TIER["Evaluate Risk Tier"]

    PATHCHECK -->|"App Launch"| APPCHK{"App in Explicit Allowlist (chrome, notepad, calc...)?"}
    APPCHK -->|"No"| DENY5["FORBIDDEN: Unapproved Executable"]
    APPCHK -->|"Yes"| TIER

    PATHCHECK -->|"Browser URL"| URLCHK{"Scheme is http:// or https://?"}
    URLCHK -->|"No (file://, chrome://, javascript:)"| DENY6["FORBIDDEN: Unsafe URL Scheme"]
    URLCHK -->|"Yes"| TIER

    PATHCHECK -->|"Keyboard Shortcut"| KEYCHK{"Contains Win, Alt+F4, Ctrl+Alt+Del, Ctrl+Shift+Esc?"}
    KEYCHK -->|"Yes"| DENY7["FORBIDDEN: Blacklisted OS Hotkey"]
    KEYCHK -->|"No"| TIER

    PATHCHECK -->|"Pure OS Setting (Brightness/Volume)"| TIER

    TIER -->|"SAFE"| RUN["Execute Tool + Log to SQLite"]
    TIER -->|"MEDIUM / HIGH"| POPUP{"User Clicks Approve in Confirmation Dialog?"}
    POPUP -->|"Yes"| RUN
    POPUP -->|"No"| CANCEL["Cancelled by User + Log to SQLite"]
```

---

## 3. End-to-End Walkthroughs (Sequence Diagrams)

### Example A: Fast Local OS Control — *"Windows, increase the brightness"*

Runs 100% on CPU in under a second without even needing the GPU LLM.

```mermaid
sequenceDiagram
    actor User
    participant Voice as Voice Listener (CPU)
    participant Brain as Fast Grammar / Needle 3 (CPU)
    participant Safety as safety/policy.py
    participant OS as os_controls.py
    participant Audit as SQLite Audit Log

    User->>Voice: Speaks "Windows, increase the brightness"
    Voice->>Voice: openWakeWord + Silero VAD + faster-whisper (int8)
    Voice->>Brain: Transcript: "increase the brightness"
    Brain->>Safety: ToolCall(adjust_brightness, delta=+20)
    Safety->>Safety: Schema valid (delta in -50..+50), Risk = SAFE
    Safety->>OS: Approved -> adjust_brightness(+20)
    OS->>OS: screen-brightness-control (WMI / DDC-CI)
    OS-->>Audit: Record transcript, tool call, new brightness level
    OS-->>User: Status: "Brightness increased to 80%"
```

### Example B: Browser Task (Chrome #1 Priority) — *"Go to Chrome and type Elon Musk"*

Uses the local Ollama model on your RTX 4050 GPU if phrased naturally (or fast grammar for standard phrasing), validates against policy, and drives real Google Chrome via Playwright.

```mermaid
sequenceDiagram
    actor User
    participant Voice as Voice Listener (CPU)
    participant Brain as Orchestrator + Ollama qwen3:4b (RTX 4050)
    participant Safety as safety/policy.py
    participant Chrome as browser.py (Playwright Chrome)
    participant Audit as SQLite Audit Log

    User->>Voice: Speaks "Go to Chrome and type Elon Musk"
    Voice->>Brain: Transcript: "Go to Chrome and type Elon Musk"
    Brain->>Brain: Emit ToolCall(chrome_search, query="Elon Musk")
    Brain->>Safety: Validate chrome_search("Elon Musk")
    Safety->>Safety: Verify Chrome allowlisted, https URL, Risk = SAFE
    Safety->>Chrome: Approved -> chrome_search("Elon Musk")
    Chrome->>Chrome: Launch/focus Google Chrome (channel="chrome")
    Chrome->>Chrome: Navigate & submit search query via DOM
    Chrome-->>Audit: Log action + result URL
    Chrome-->>User: Status: "Opened Chrome and searched for Elon Musk"
```

---

## 4. Hardware Split & MCP Ecosystem Topology

How **LocalGuardian** splits workloads across your **Ryzen 7 7840HS + RTX 4050 (6 GB VRAM)** and exposes its sandboxed tools via **Model Context Protocol (MCP)**.

```mermaid
flowchart LR
    subgraph CPU["AMD Ryzen 7 7840HS (CPU / 16 GB RAM)"]
        V["openWakeWord + Silero VAD + faster-whisper (~400 MB RAM)"]
        G["Fast Grammar + Optional Cactus Needle 3 (~35 MB RAM)"]
        P["Safety Policy + Audit SQLite + Tray UI"]
    end

    subgraph GPU["NVIDIA RTX 4050 Laptop GPU (6 GB VRAM)"]
        LLM["Ollama: qwen3:4b (~2.6 GB VRAM) or qwen3:8b (~5.2 GB VRAM)"]
    end

    subgraph MCP["LocalGuardian FastMCP Server (Standard User)"]
        T1["adjust_brightness / set_brightness"]
        T2["adjust_volume / toggle_mute"]
        T3["open_allowlisted_app"]
        T4["chrome_open_url / chrome_search (Chrome #1)"]
        T5["uia_click / uia_type (Sandboxed Window)"]
    end

    subgraph EXTERNAL["Optional External MCP Clients"]
        EXT["LM Studio / Claude Desktop / VS Code / Cursor"]
    end

    V --> G
    G -->|"Complex Task"| LLM
    G -->|"Simple Task"| P
    LLM --> P
    P -->|"Approved Only"| MCP
    EXT -.->|"Optional stdio MCP"| P
```

---

## 5. Prototype Build Order (4 Steps)

```mermaid
flowchart LR
    S1["Step 1: Scaffold + Hard Safety Core + Adversarial pytest Suite"] --> S2["Step 2: OS Controls (Brightness/Volume) + Chrome Playwright + --dry-run"]
    S2 --> S3["Step 3: Fast Grammar + Ollama qwen3:4b + FastMCP Server"]
    S3 --> S4["Step 4: Local Voice (faster-whisper PTT -> openWakeWord Hands-Free)"]
```
