"""Build agent helper for generating and validating structured JSON files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import urllib.error
import urllib.request

REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_CASE_KEYS: dict[str, type] = {
    "case_id": str,
    "title": str,
    "evidence": list,
    "decisions": list,
    "hints": list,
    "conclusion": dict,
}


def safe_path(rel_path: str) -> Path:
    """Resolve rel_path within REPO_ROOT and reject traversal outside the repo."""
    candidate = (REPO_ROOT / rel_path).resolve()
    root_resolved = REPO_ROOT.resolve()
    if candidate == root_resolved or root_resolved not in candidate.parents:
        raise ValueError(f"Path escapes repository root: {rel_path}")
    return candidate


def _validate_generated_json(rel_path: str, parsed: object) -> str | None:
    """Validate general JSON structure and required case fields for cases/*.json."""
    if not isinstance(parsed, dict):
        return "Generated JSON root must be a JSON object."

    target_parts = Path(rel_path).parts
    if "cases" in target_parts:
        missing = [key for key in REQUIRED_CASE_KEYS if key not in parsed]
        if missing:
            return f"Case JSON is missing required keys: {', '.join(missing)}"

        for key, expected_type in REQUIRED_CASE_KEYS.items():
            value = parsed[key]
            if not isinstance(value, expected_type):
                return f"Case field '{key}' must be {expected_type.__name__}."
            if expected_type is str and not value.strip():
                return f"Case field '{key}' cannot be empty."
            if expected_type in (list, dict) and len(value) == 0:
                return f"Case field '{key}' cannot be empty."

    return None


def tool_generate_json(
    rel_path: str,
    instructions: str,
    model: str,
    base_url: str,
    spec_text: str = "",
) -> str:
    """Request a JSON object from Ollama, validate it, and write it inside REPO_ROOT."""
    cleaned_instructions = (instructions or "").strip()
    if len(cleaned_instructions) < 8 or cleaned_instructions in {"{", "[", "{}"}:
        return (
            "Invalid or incomplete instructions for generate_json. "
            "Provide clear schema and content instructions describing the JSON file to generate."
        )

    target = safe_path(rel_path)

    system_prompt = (
        "You are generating a structured JSON file for Cyber Detective, an educational "
        "cybersecurity investigation game. Return ONLY a single valid JSON object using "
        "double quotes that matches the requested schema and instructions. "
        "Use strictly fictional, classroom-safe simulated data (fictional users, simulated "
        "incidents, and documentation-safe addresses); never include real exploits, "
        "live attacks, or real malware."
    )
    if spec_text.strip():
        system_prompt += f"\n\n=== REFERENCE SPEC ===\n{spec_text.strip()}"

    payload = {
        "model": model,
        "format": "json",
        "stream": False,
        "options": {"num_ctx": 4096},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": cleaned_instructions},
        ],
    }

    endpoint = f"{base_url.rstrip('/')}/api/chat"
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=240) as resp:
            response_data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        return f"Could not reach Ollama at {base_url}: {exc}"
    except json.JSONDecodeError as exc:
        return f"Invalid response envelope from Ollama: {exc}"

    raw_content = response_data.get("message", {}).get("content", "")
    try:
        parsed = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        return f"Model returned invalid JSON: {exc}"

    validation_error = _validate_generated_json(rel_path, parsed)
    if validation_error:
        return f"Generated JSON failed validation for {rel_path}: {validation_error}"

    formatted = json.dumps(parsed, indent=2) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(formatted, encoding="utf-8")
    return f"Generated valid JSON at {rel_path} ({len(formatted)} chars)"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and validate a JSON artifact via Ollama.")
    parser.add_argument("--output", required=True, help="Target path relative to repo root, e.g. cases/network_breach.json")
    parser.add_argument("--instructions", required=True, help="Schema and content instructions for the JSON object")
    parser.add_argument("--spec-file", default="", help="Optional path relative to repo root with schema/design notes")
    parser.add_argument("--model", default="llama3.1", help="Ollama model name")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434", help="Ollama base URL")
    args = parser.parse_args()

    spec_text = ""
    if args.spec_file:
        spec_text = safe_path(args.spec_file).read_text(encoding="utf-8")

    result = tool_generate_json(
        rel_path=args.output,
        instructions=args.instructions,
        model=args.model,
        base_url=args.base_url,
        spec_text=spec_text,
    )
    print(result)


if __name__ == "__main__":
    main()