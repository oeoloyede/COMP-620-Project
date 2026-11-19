import argparse
import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MAX_STEPS = 8

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and directories under a relative path inside the repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subdir": {
                        "type": "string",
                        "description": "Relative directory path (default '.').",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file inside the repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rel_path": {
                        "type": "string",
                        "description": "Relative path to the file.",
                    }
                },
                "required": ["rel_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file inside the repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rel_path": {
                        "type": "string",
                        "description": "Relative path to the file.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full text content to write.",
                    },
                },
                "required": ["rel_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_pytest",
            "description": "Run pytest inside the backend directory and return stdout/stderr.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Optional test path or pytest args (e.g. 'tests/test_engine.py').",
                    }
                },
                "required": [],
            },
        },
    },
]


def safe_path(rel_path: str) -> Path:
    resolved = (REPO_ROOT / rel_path).resolve()
    if resolved != REPO_ROOT and REPO_ROOT not in resolved.parents:
        raise ValueError(f"Path escapes repository root: {rel_path}")
    return resolved


def tool_list_files(subdir: str = ".") -> str:
    target = safe_path(subdir)
    if not target.exists():
        return f"Directory does not exist: {subdir}"
    ignore_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}
    entries = []
    for root, dirs, files in os.walk(target):
        dirs[:] = [d for d in sorted(dirs) if d not in ignore_dirs]
        for name in sorted(files):
            p = Path(root) / name
            entries.append(str(p.relative_to(REPO_ROOT)))
    return "\n".join(entries) if entries else "(no files)"


def tool_read_file(rel_path: str) -> str:
    target = safe_path(rel_path)
    if not target.exists() or not target.is_file():
        return f"File not found: {rel_path}"
    return target.read_text(encoding="utf-8")


def tool_write_file(rel_path: str, content: str) -> str:
    target = safe_path(rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Wrote {rel_path} ({len(content)} chars)"


def tool_run_pytest(target: str = "") -> str:
    backend_dir = REPO_ROOT / "backend"
    if not backend_dir.exists():
        return "Backend directory does not exist yet."
    cmd = ["pytest"] + (target.split() if target.strip() else [])
    proc = subprocess.run(
        cmd,
        cwd=backend_dir,
        capture_output=True,
        text=True,
        timeout=60,
    )
    output = f"Exit code: {proc.returncode}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    return output[-4000:]


def execute_tool(name: str, args: dict) -> str:
    try:
        if name == "list_files":
            return tool_list_files(args.get("subdir", "."))
        if name == "read_file":
            return tool_read_file(args["rel_path"])
        if name == "write_file":
            return tool_write_file(args["rel_path"], args["content"])
        if name == "run_pytest":
            return tool_run_pytest(args.get("target", ""))
        return f"Unknown tool: {name}"
    except Exception as exc:
        return f"Tool error ({name}): {exc}"


def call_ollama(messages: list[dict], model: str, base_url: str) -> dict:
    payload = {
        "model": model,
        "messages": messages,
        "tools": TOOLS,
        "stream": False,
    }
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Ollama at {base_url}: {exc}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Llama agent for building Cyber Detective.")
    parser.add_argument("task", help="Scoped task for the Llama agent to execute.")
    parser.add_argument("--max-steps", type=int, default=MAX_STEPS)
    args = parser.parse_args()

    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "llama3.1")

    spec_text = ""
    spec_path = REPO_ROOT / "AGENT_SPEC.md"
    if spec_path.exists():
        spec_text = spec_path.read_text(encoding="utf-8")

    system_prompt = (
        "You are a software-building agent helping create Cyber Detective, "
        "a classroom-safe cybersecurity investigation web/Python game. "
        "Follow AGENT_SPEC.md strictly. Use tools to inspect and write files or run pytest. "
        "Do not alter existing test assertions just to make tests pass.\n\n"
        f"=== AGENT_SPEC.md ===\n{spec_text}"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": args.task},
    ]

    for step in range(1, args.max_steps + 1):
        print(f"\n--- Agent Step {step}/{args.max_steps} ---")
        data = call_ollama(messages, model=model, base_url=base_url)
        msg = data.get("message", {})
        messages.append(msg)

        tool_calls = msg.get("tool_calls") or []
        content = msg.get("content", "")
        if content:
            print(content)

        if not tool_calls:
            print("\nAgent finished task.")
            return

        for call in tool_calls:
            fn = call.get("function", {})
            fn_name = fn.get("name", "")
            raw_args = fn.get("arguments", {})
            fn_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            print(f"[Tool] {fn_name}({fn_args})")
            result = execute_tool(fn_name, fn_args)
            messages.append({"role": "tool", "content": result})

    print("\nReached max steps without final response.")


if __name__ == "__main__":
    main()
