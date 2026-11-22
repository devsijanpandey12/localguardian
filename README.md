# LocalGuardian

**Voice-Driven Local LLM Agent for Sandboxed Windows OS and Browser Automation**

LocalGuardian lets you control Windows (display brightness, volume, allowlisted apps) and **Google Chrome** (#1 priority browser) using natural voice or text commands—powered by local models (`faster-whisper` on CPU + Ollama `qwen3:4b` on GPU) behind a **hard-coded Python safety sandbox** that can never touch `C:\Windows`, `C:\Program Files`, Registry, or raw PowerShell.

## Documentation

- [PROTOTYPE.md](./PROTOTYPE.md) — Exact breakdown of what is built in this prototype and why each library/model was chosen.
- [FLOWCHART_RESEARCH.md](./FLOWCHART_RESEARCH.md) — End-to-end architecture, safety decision tree, and sequence flowcharts.
- [RESEARCH.md](./RESEARCH.md) — Full research blueprint, SOTA model comparisons, hardware profiles, and roadmap.

## Quickstart (Anaconda on Windows)

```powershell
# 1. Activate the dedicated Conda environment
conda activate localguardian

# 2. Install LocalGuardian with Chrome, MCP, voice, and dev tools
pip install -e ".[browser,mcp,voice,dev]"

# 3. Verify safety policy, Chrome detection, audio/brightness APIs, and Ollama
localguardian --doctor

# 4. Run the automated safety & prototype test suite
pytest

# 5. Test safely in Dry-Run text mode first (no real changes)
localguardian --text --dry-run

# 6. Run live text commands
localguardian --text
# Try:
#   Windows, increase the brightness
#   go to Chrome and type Elon Musk
#   delete C:\Windows\System32        <-- watch the hard safety block!

# 7. Run push-to-talk local voice mode (faster-whisper on CPU)
localguardian --voice

# 8. Optional: enable Tier-2 local LLM for casual/multi-step commands
winget install Ollama.Ollama
ollama pull qwen3:4b

# 9. Optional: expose sandboxed Windows & Chrome tools over MCP
localguardian --mcp
```

## Core Safety Guarantees

- Runs as a **standard non-admin user** (never requests UAC elevation).
- **Zero raw PowerShell/cmd execution**—the LLM only sees narrow, strictly typed Python tools.
- Hard-coded blocks on `C:\Windows`, `C:\Program Files`, `C:\Program Files (x86)`, `C:\ProgramData`, `AppData`, Windows Registry, credential stores, unsafe URL schemes (`file://`, `chrome://`, `javascript:`), and OS hotkeys (`Win+*`, `Alt+F4`, `Ctrl+Alt+Del`).
- Every command and policy decision is logged locally to `~/.localguardian/audit.db` (`localguardian --audit`).

## License

MIT — see [LICENSE](./LICENSE).
