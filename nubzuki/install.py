"""Register `nubzuki mcp` with Claude Code, the Claude app, Codex, Gemini CLI and Cursor."""
import json
import os
import re
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


def codex_config():
    home = os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")
    return os.path.join(home, "config.toml")


def gemini_config():
    return os.path.join(os.path.expanduser("~"), ".gemini", "settings.json")


def _backup_and_write(path, text):
    """Replace another app's config safely: keep a .bak, write atomically, keep the file's permissions
    (Codex and Claude configs can hold API keys and are often mode 600)."""
    tmp = path + ".nubzuki-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak")
        shutil.copymode(path, tmp)
    os.replace(tmp, path)


def add_to_toml(path, cmd, args):
    """Add or replace [mcp_servers.nubzuki] in Codex's config.toml, leaving the rest of the file as is."""
    text = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            text = f.read()
    # JSON string and array syntax is valid TOML for plain strings
    block = f"[mcp_servers.{NAME}]\ncommand = {json.dumps(cmd)}\nargs = {json.dumps(args)}\n"
    m = re.search(rf"""(?ms)^\[\s*mcp_servers\s*\.\s*["']?{NAME}["']?\s*\]\s*\n.*?(?=^\[|\Z)""", text)
    if m and m.group(0).strip() == block.strip():
        return "same"
    if m:
        rest = text[m.end():]
        text, status = text[:m.start()] + block + ("\n" if rest else "") + rest, "updated"
    else:
        sep = "" if not text else ("\n" if text.endswith("\n") else "\n\n")
        text, status = text + sep + block, "added"
    _backup_and_write(path, text)
    return status


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
    _backup_and_write(path, json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
    return status


def allow_tools(ws_path):
    """Let Claude Code sessions started in the semester folder call nubzuki tools without a prompt each time."""
    path = os.path.join(ws_path, ".claude", "settings.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cfg = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    allow = cfg.setdefault("permissions", {}).setdefault("allow", [])
    if f"mcp__{NAME}" in allow:
        return False
    allow.append(f"mcp__{NAME}")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return True


def claude_code_has_server():
    claude = shutil.which("claude")
    return bool(claude) and subprocess.run([claude, "mcp", "get", NAME], capture_output=True).returncode == 0


def add_to_claude_code(cmd, args):
    claude = shutil.which("claude")
    if not claude:
        return None
    try:
        with open(os.path.join(os.path.expanduser("~"), ".claude.json"), encoding="utf-8") as f:
            entry = json.load(f).get("mcpServers", {}).get(NAME, {})
        if entry.get("command") == cmd and entry.get("args") == args:
            return "same"
    except (OSError, ValueError, AttributeError):
        pass
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
            if st == "same":
                done += 1
                out("  ✓ Claude Code: already set up.")
            elif st:
                done += 1
                out("  ✓ Claude Code: registered for all projects. Start a new `claude` session to use it.")
            elif targets:
                out("  - Claude Code: `claude` command not found.")

    for key, label, path, write, hint in (
            ("claude-app", "Claude app", desktop_config(), add_to_json, "Quit the Claude app completely (⌘Q / Exit) and reopen it."),
            ("codex", "Codex", codex_config(), add_to_toml, "Restart the Codex app, or start a new `codex` session."),
            ("gemini", "Gemini CLI", gemini_config(), add_to_json, "Start a new `gemini` session."),
            ("cursor", "Cursor", cursor_config(), add_to_json, "Restart Cursor.")):
        if not want(key):
            continue
        if not os.path.isdir(os.path.dirname(path)):
            if targets:
                out(f"  - {label}: not installed ({os.path.dirname(path)} not found).")
            continue
        try:
            st = write(path, cmd, args)
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
