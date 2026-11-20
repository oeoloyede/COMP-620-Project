import argparse
import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MAX_STEPS = 8


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
    if target.suffix.lower() == ".json":
        try:
            parsed = json.loads(content)
            content = json.dumps(parsed, indent=2)
        except json.JSONDecodeError as exc:
            return (
                f"Invalid JSON for {rel_path}: {exc}. "
                "For .json files, prefer generate_json or provide complete, valid JSON using double quotes."
            )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Wrote {rel_path} ({len(content)} chars)"


def tool_generate_json(rel_path: str, instructions: str, model: str, base_url: str, spec_text: str) -> str:
    target = safe_path(rel_path)
    payload = {
        "model": model,
        "format": "json",
        "stream": False,
        "options": {"num_ctx": 4096},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are generating a structured JSON file for Cyber Detective. "
                    "Return ONLY a single valid JSON object with double quotes matching the instructions and spec. "
                    "Use strictly fictional, classroom-safe simulated data.\n\n"
                    f"=== SPEC ===\n{spec_text}"
                ),
            },
            {"role": "user", "content": instructions},
        ],
    }
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=240) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        return f"Could not reach Ollama at {base_url}: {exc}"

    raw = data.get("message", {}).get("content", "")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return f"Model returned invalid JSON: {exc}"

    formatted = json.dumps(parsed, indent=2)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(formatted, encoding="utf-8")
    return f"Generated valid JSON at {rel_path} ({len(formatted)} chars)"


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


def build_tools_schema() -> list[dict]:
    return [
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
                "description": "Create or overwrite a non-JSON text/code file with complete content.",
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
                "name": "generate_json",
                "description": "Generate and save a valid JSON file directly using Ollama JSON mode.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "rel_path": {
                            "type": "string",
                            "description": "Target relative .json path (e.g. 'cases/suspicious_email.json').",
                        },
                        "instructions": {
                            "type": "string",
                            "description": "Detailed schema and content instructions for the JSON file.",
                        },
                    },
                    "required": ["rel_path", "instructions"],
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
                            "description": "Optional test path or pytest args.",
                        }
                    },
                    "required": [],
                },
            },
        },
    ]


def call_ollama(messages: list[dict], tools: list[dict], model: str, base_url: str) -> dict:
    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "stream": False,
        "options": {"num_ctx": 4096},
    }
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=240) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Ollama at {base_url}: {exc}") from exc


def looks_like_pseudo_tool(text: str) -> bool:
    stripped = text.strip()
    if not stripped.startswith("{"):
        return False
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        return '"name"' in stripped or "'name'" in stripped
    return isinstance(obj, dict) and ("name" in obj or "parameters" in obj)


def main() -> None:
    parser = argparse.ArgumentParser(description="Llama agent for building Cyber Detective.")
    parser.add_argument("--task-file", help="Path to a text file containing the task prompt.")
    parser.add_argument("task", nargs="?", help="Scoped task for the Llama agent to execute.")
    parser.add_argument("--max-steps", type=int, default=MAX_STEPS)
    args = parser.parse_args()

    if args.task_file:
        task_text = Path(args.task_file).read_text(encoding="utf-8").strip()
    elif args.task:
        task_text = args.task.strip()
    else:
        parser.error("Provide either a task string or --task-file.")

    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "llama3.1")

    spec_text = ""
    spec_path = REPO_ROOT / "AGENT_SPEC.md"
    if spec_path.exists():
        spec_text = spec_path.read_text(encoding="utf-8")

    tools = build_tools_schema()
    system_prompt = (
        "You are a software-building agent helping create Cyber Detective, "
        "a classroom-safe cybersecurity investigation web/Python game. "
        "Use generate_json for .json files and write_file for code/text files. "
        "Never output raw JSON tool calls or fake tool names like 'echo' as plain text. "
        "Do not alter existing test assertions just to make tests pass.\n\n"
        f"=== AGENT_SPEC.md ===\n{spec_text}"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task_text},
    ]
    generated_files: set[str] = set()

    for step in range(1, args.max_steps + 1):
        print(f"\n--- Agent Step {step}/{args.max_steps} ---")
        data = call_ollama(messages, tools=tools, model=model, base_url=base_url)
        msg = data.get("message", {})
        messages.append(msg)

        tool_calls = msg.get("tool_calls") or []
        content = msg.get("content", "")
        if content:
            print(content)

        if not tool_calls:
            if looks_like_pseudo_tool(content):
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Do not print JSON tool text directly. Call the appropriate tool "
                            "(such as generate_json for .json files), or summarize once completed."
                        ),
                    }
                )
                continue
            print("\nAgent finished task.")
            return

        for call in tool_calls:
            fn = call.get("function", {})
            fn_name = fn.get("name", "")
            raw_args = fn.get("arguments", {})
            fn_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            print(f"[Tool] {fn_name}({fn_args})")

            if fn_name == "generate_json":
                rel_path = fn_args["rel_path"]
                norm_path = str(safe_path(rel_path))
                if norm_path in generated_files:
                    result = (
                        f"Already generated {rel_path} in this run. "
                        "Do not call generate_json again for this file; provide your final summary now."
                    )
                else:
                    result = tool_generate_json(
                        rel_path=rel_path,
                        instructions=fn_args["instructions"],
                        model=model,
                        base_url=base_url,
                        spec_text=spec_text,
                    )
                    if result.startswith("Generated valid JSON"):
                        generated_files.add(norm_path)
            else:
                try:
                    if fn_name == "list_files":
                        result = tool_list_files(fn_args.get("subdir", "."))
                    elif fn_name == "read_file":
                        result = tool_read_file(fn_args["rel_path"])
                    elif fn_name == "write_file":
                        result = tool_write_file(fn_args["rel_path"], fn_args["content"])
                    elif fn_name == "run_pytest":
                        result = tool_run_pytest(fn_args.get("target", ""))
                    else:
                        result = f"Unknown tool: {fn_name}"
                except Exception as exc:
                    result = f"Tool error ({fn_name}): {exc}"

            messages.append({"role": "tool", "content": result})

    print("\nReached max steps without final response.")


if __name__ == "__main__":
    main()