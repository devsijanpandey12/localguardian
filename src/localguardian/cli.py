"""LocalGuardian CLI entry point (`localguardian`).

Modes:
    localguardian --doctor               Verify hardware, safety blocks, Chrome, Ollama, voice
    localguardian --text [--dry-run]     Interactive text command console
    localguardian --voice [--dry-run]    Push-to-talk local voice command console (faster-whisper CPU)
    localguardian --once "<cmd>"         Execute a single command and exit
    localguardian --mcp [--dry-run]      Start FastMCP stdio server
    localguardian --audit                Show recent local SQLite audit log entries
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from localguardian import __version__
from localguardian.brain.llm_planner import LocalLLMPlanner
from localguardian.brain.orchestrator import LocalGuardianOrchestrator
from localguardian.config import LocalGuardianConfig, load_config
from localguardian.safety.audit import AuditLogger
from localguardian.safety.confirm import ConfirmationChannel, ConfirmationManager
from localguardian.safety.policy import SafetyPolicy, is_running_as_admin
from localguardian.tools.browser import find_chrome_executable
from localguardian.tools.registry import ToolRegistry


def _build_runtime(
    config: LocalGuardianConfig,
    *,
    dry_run: bool = False,
    confirm_channel: ConfirmationChannel = ConfirmationChannel.DIALOG,
    oneshot: bool = False,
):
    if dry_run:
        config.safety.dry_run = True
    policy = SafetyPolicy(config)
    audit = AuditLogger(config.audit_db_path)
    confirm = ConfirmationManager(confirm_channel)
    registry = ToolRegistry(
        config,
        policy,
        audit,
        confirm,
        keep_browser_open_on_oneshot=oneshot,
    )
    orchestrator = LocalGuardianOrchestrator(config, registry)
    return policy, audit, registry, orchestrator


def run_doctor(config: LocalGuardianConfig) -> int:
    """Verify environment, Chrome #1 priority, safety core, Ollama, and voice packages."""
    print(f"LocalGuardian v{__version__} — System & Safety Doctor")
    print("=" * 60)

    # 1. Python & Privilege check
    admin = is_running_as_admin()
    print(f"[{'WARN' if admin else 'OK  '}] Python {sys.version.split()[0]} | Admin privilege: {admin} (recommended: False)")

    # 2. Safety self-test
    policy = SafetyPolicy(config)
    checks = [
        ("Block C:\\Windows", not policy.check_path(r"C:\Windows\System32\cmd.exe", write=True).allowed),
        ("Block C:\\Program Files", not policy.check_path(r"C:\Program Files\test.txt", write=True).allowed),
        ("Block raw PowerShell", not policy.evaluate("run_powershell", {"command": "dir"}).allowed),
        ("Block Win+R hotkey", not policy.evaluate("send_hotkey", {"keys": ["win", "r"]}).allowed),
        ("Allow Chrome search", policy.evaluate("chrome_search", {"query": "Elon Musk"}).allowed),
        ("Allow brightness +20", policy.evaluate("adjust_brightness", {"delta": 20}).allowed),
    ]
    all_safe = True
    for label, passed in checks:
        tag = "OK  " if passed else "FAIL"
        if not passed:
            all_safe = False
        print(f"[{tag}] Safety check — {label}")

    # 3. Google Chrome (#1 priority browser)
    chrome_exe = find_chrome_executable(config)
    print(f"[{'OK  ' if chrome_exe else 'WARN'}] Chrome (#1 priority): {chrome_exe or 'Not found in standard paths'}")

    # 4. Optional Python libraries
    for mod_name, label in [
        ("screen_brightness_control", "Brightness API (screen-brightness-control)"),
        ("pycaw", "Audio API (pycaw)"),
        ("playwright", "Browser Automation (playwright)"),
        ("mcp", "MCP Server SDK (mcp / FastMCP)"),
        ("faster_whisper", "Offline Voice STT (faster-whisper)"),
        ("sounddevice", "Microphone Capture (sounddevice)"),
    ]:
        try:
            __import__(mod_name)
            print(f"[OK  ] {label}: installed")
        except Exception:
            print(f"[MISS] {label}: not installed")

    # 5. Ollama local LLM
    planner = LocalLLMPlanner(config)
    ok, models, msg = planner.health_check()
    print(f"[{'OK  ' if ok else 'INFO'}] Ollama LLM ({config.llm.model}): {msg}")
    if models:
        print(f"       Available Ollama models: {', '.join(models)}")

    print(f"[OK  ] Audit DB path: {config.audit_db_path}")
    print("=" * 60)
    return 0 if all_safe else 1


def run_models_info(config: LocalGuardianConfig) -> int:
    """Display configured and live local model details (LLM, voice STT, Ollama status)."""
    import httpx

    print(f"LocalGuardian v{__version__} — Active Models & Runtime")
    print("=" * 60)
    print("Tier 1 (Fast Router) : Deterministic Fast Grammar (CPU, <1 ms)")
    print(f"Tier 2 (Local LLM)   : {config.llm.provider} -> {config.llm.model} ({config.llm.base_url})")
    print(f"Voice STT            : {config.voice.stt_backend} ({config.voice.stt_model}, device={config.voice.stt_device}, compute={config.voice.stt_compute_type})")
    print(f"Browser Priority     : {config.browser.priority} (fallback: {config.browser.fallback})")

    planner = LocalLLMPlanner(config)
    ok, models, msg = planner.health_check()
    print(f"Ollama Status        : {'ONLINE' if ok else 'OFFLINE'} — {msg}")

    if ok:
        base = config.llm.base_url.rstrip("/")
        root = base[:-3] if base.endswith("/v1") else base
        print(f"Installed Models     : {', '.join(models) if models else '(none pulled yet)'}")
        try:
            with httpx.Client(timeout=4.0) as client:
                show = client.post(f"{root}/api/show", json={"name": config.llm.model})
                if show.status_code == 200:
                    details = show.json().get("details") or {}
                    print(
                        "Configured Model Info: "
                        f"family={details.get('family', '?')} | "
                        f"params={details.get('parameter_size', '?')} | "
                        f"quant={details.get('quantization_level', '?')} | "
                        f"format={details.get('format', '?')}"
                    )
                ps = client.get(f"{root}/api/ps")
                if ps.status_code == 200:
                    running = ps.json().get("models") or []
                    if running:
                        for rm in running:
                            vram_mb = round(rm.get("size_vram", 0) / (1024 * 1024))
                            total_mb = round(rm.get("size", 0) / (1024 * 1024))
                            print(f"Loaded in Memory     : {rm.get('name')} ({vram_mb} MB VRAM / {total_mb} MB total)")
                    else:
                        print("Loaded in Memory     : (idle — loads onto GPU automatically on first Tier-2 prompt)")
        except Exception as exc:
            print(f"Model Details Error  : {exc}")
    print("=" * 60)
    return 0


def run_text_repl(config: LocalGuardianConfig, *, dry_run: bool = False) -> int:
    _policy, _audit, registry, orchestrator = _build_runtime(
        config,
        dry_run=dry_run,
        confirm_channel=ConfirmationChannel.CLI,
        oneshot=False,
    )
    mode_tag = " [DRY-RUN]" if dry_run else ""
    print(f"LocalGuardian v{__version__} — Interactive Text Mode{mode_tag}")
    print(f"Models: Tier-1 Fast Grammar (CPU) -> Tier-2 {config.llm.provider}/{config.llm.model} | Browser #1: {config.browser.priority}")
    print("Try: 'Windows, increase the brightness' | 'go to Chrome and type Elon Musk' | 'delete C:\\Windows'")
    print("Type 'exit' or 'quit' to stop.\n")

    try:
        while True:
            try:
                cmd = input("localguardian> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not cmd:
                continue
            if cmd.lower() in {"exit", "quit", "q"}:
                break
            res = orchestrator.handle(cmd, dry_run=dry_run)
            print(f"  [{res.route_tier}] {res.message}\n")
    finally:
        registry.close()
    return 0


def run_voice_repl(config: LocalGuardianConfig, *, dry_run: bool = False) -> int:
    from localguardian.voice.listener import PushToTalkListener
    from localguardian.voice.stt import LocalTranscriber

    _policy, _audit, registry, orchestrator = _build_runtime(
        config,
        dry_run=dry_run,
        confirm_channel=ConfirmationChannel.DIALOG,
        oneshot=False,
    )
    listener = PushToTalkListener(config)
    stt = LocalTranscriber(config)
    mode_tag = " [DRY-RUN]" if dry_run else ""
    print(f"LocalGuardian v{__version__} — Local Voice Mode (faster-whisper {config.voice.stt_model} on {config.voice.stt_device}){mode_tag}")
    print("Press ENTER to start speaking, press ENTER again to finish, or Ctrl+C to quit.\n")

    try:
        while True:
            try:
                go = input("Press ENTER to record (or type 'q' to quit): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if go in {"q", "quit", "exit"}:
                break
            audio = listener.record_until_enter()
            if audio is None:
                print("  No audio captured.\n")
                continue
            print("  Transcribing locally on CPU...")
            transcript = stt.transcribe_array(audio)
            print(f"  Heard: {transcript!r}")
            if not transcript:
                print("  Nothing understood.\n")
                continue
            res = orchestrator.handle(transcript, dry_run=dry_run)
            print(f"  [{res.route_tier}] {res.message}\n")
    finally:
        registry.close()
    return 0


def run_audit_view(config: LocalGuardianConfig, limit: int = 15) -> int:
    audit = AuditLogger(config.audit_db_path)
    entries = audit.recent(limit=limit)
    if not entries:
        print("No audit entries recorded yet.")
        return 0
    for e in entries:
        dry = " (dry)" if e.dry_run and e.status != "dry_run" else ""
        print(
            f"#{e.id} [{e.timestamp[:19]}] {e.status.upper()}{dry} | "
            f"{e.route_tier} -> {e.tool_name}({e.args_json}) | "
            f"risk={e.risk_level} ({e.rule_id}) | {e.message}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="localguardian",
        description="LocalGuardian: Voice-driven local LLM agent for sandboxed Windows OS & Chrome automation.",
    )
    parser.add_argument("--config", type=str, default=None, help="Path to YAML config file.")
    parser.add_argument("--dry-run", action="store_true", help="Simulate tool execution without changing Windows.")
    parser.add_argument("--doctor", action="store_true", help="Run system, safety, Chrome, and Ollama self-checks.")
    parser.add_argument("--models", action="store_true", help="Show active local LLM, STT, and Ollama VRAM details.")
    parser.add_argument("--text", action="store_true", help="Start interactive text command console.")
    parser.add_argument("--voice", action="store_true", help="Start push-to-talk local voice mode.")
    parser.add_argument("--once", type=str, default=None, help="Execute a single command and exit.")
    parser.add_argument("--mcp", action="store_true", help="Run LocalGuardian as a FastMCP stdio server.")
    parser.add_argument("--audit", action="store_true", help="Display recent SQLite audit log entries.")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)

    if args.doctor:
        return run_doctor(config)
    if args.models:
        return run_models_info(config)
    if args.audit:
        return run_audit_view(config)
    if args.mcp:
        from localguardian.mcp_server import run_mcp_server

        run_mcp_server(config, dry_run=args.dry_run)
        return 0
    if args.once:
        _policy, _audit, registry, orchestrator = _build_runtime(
            config,
            dry_run=args.dry_run,
            confirm_channel=ConfirmationChannel.CLI,
            oneshot=True,
        )
        try:
            res = orchestrator.handle(args.once, dry_run=args.dry_run)
            print(f"[{res.route_tier}] {res.message}")
            return 0
        finally:
            registry.close()
    if args.voice:
        return run_voice_repl(config, dry_run=args.dry_run)

    # Default to interactive text mode when run directly
    return run_text_repl(config, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
