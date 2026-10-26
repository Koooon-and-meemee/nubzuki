"""Register `nubzuki mcp` with Claude Code, the Claude app and Cursor."""
import json
import os
import shutil
import subprocess
import sys

NAME = "nubzuki"


def server_command():
    exe = shutil.which(NAME)
    if exe:
        return os.path.abspath(exe), ["mcp"]
    return sys.executable, ["-m", NAME, "mcp"]


def desktop_config():
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif os.name == "nt":
        base = os.environ.get("APPDATA", os.path.expanduser("~\\AppData\\Roaming"))
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(base, "Claude", "claude_desktop_config.json")


def cursor_config():
    return os.path.join(os.path.expanduser("~"), ".cursor", "mcp.json")


def add_to_json(path, cmd, args):
    """Add the server to an mcpServers JSON file, keeping everything else. Returns 'added', 'updated' or 'same'."""
    cfg = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            text = f.read().strip()
        cfg = json.loads(text) if text else {}
    entry = {"command": cmd, "args": args}
    servers = cfg.setdefault("mcpServers", {})
    if servers.get(NAME) == entry:
        return "same"
    status = "updated" if NAME in servers else "added"
    servers[NAME] = entry
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return status


def add_to_claude_code(cmd, args):
    claude = shutil.which("claude")
    if not claude:
        return None
    subprocess.run([claude, "mcp", "remove", NAME, "-s", "user"], capture_output=True)
    r = subprocess.run([claude, "mcp", "add", NAME, "-s", "user", "--", cmd, *args], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip())
    return "added"


def install(targets=None, out=print):
    cmd, args = server_command()
    out(f"MCP server command: {cmd} {' '.join(args)}\n")
    done = 0
    want = lambda t: not targets or t in targets

    if want("claude-code"):
        try:
            st = add_to_claude_code(cmd, args)
        except RuntimeError as e:
            out(f"  ✗ Claude Code: {e}")
        else:
            if st:
                done += 1
                out("  ✓ Claude Code: registered for all projects. Start a new `claude` session to use it.")
            elif targets:
                out("  - Claude Code: `claude` command not found.")

    for key, label, path, hint in (
            ("claude-app", "Claude app", desktop_config(), "Quit the Claude app completely (⌘Q / Exit) and reopen it."),
            ("cursor", "Cursor", cursor_config(), "Restart Cursor.")):
        if not want(key):
            continue
        if not os.path.isdir(os.path.dirname(path)):
            if targets:
                out(f"  - {label}: not installed ({os.path.dirname(path)} not found).")
            continue
        try:
            st = add_to_json(path, cmd, args)
        except (OSError, ValueError) as e:
            out(f"  ✗ {label}: could not update {path}: {e}")
            continue
        done += 1
        if st == "same":
            out(f"  ✓ {label}: already set up.")
        else:
            out(f"  ✓ {label}: {st} in {path}" + (" (backup: .bak)" if os.path.exists(path + ".bak") else ""))
            out(f"      {hint}")

    if not done:
        out("No supported app found. Add this to your MCP client's config:\n"
            + json.dumps({"mcpServers": {NAME: {"command": cmd, "args": args}}}, indent=2))
    return done
