"""Local browser preview of Cyber Detective cases."""
import argparse
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path
import secrets
from string import Template
from urllib.parse import parse_qs, urlparse
import webbrowser

from .app.engine import GameEngine

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASE = "suspicious_email"
PLAYER = "local-demo"


class Demo(BaseHTTPRequestHandler):
    def form(self, action, fields, label):
        return (
            f'<form method="post" action="/{action}">'
            f'<input type="hidden" name="token" value="{self.server.token}">'
            f'{fields}<button>{escape(label)}</button></form>'
        )

    def _current_case_id(self, raw_case_id: str | None) -> str:
        cases = self.server.engine.list_cases(PLAYER)
        valid_ids = [item["case_id"] for item in cases]
        if raw_case_id in valid_ids:
            return raw_case_id
        if DEFAULT_CASE in valid_ids:
            return DEFAULT_CASE
        return valid_ids[0] if valid_ids else DEFAULT_CASE

    def do_GET(self):
        parsed = urlparse(self.path)
        if self.headers.get("Host") != self.server.address or parsed.path != "/":
            self.send_error(404)
            return

        engine = self.server.engine
        query_case = parse_qs(parsed.query).get("case", [None])[0]
        all_cases = engine.list_cases(PLAYER)
        case_id = self._current_case_id(query_case)

        progress = engine.get_player_progress(PLAYER)["investigations"]
        state = next((entry for entry in progress if entry["case_id"] == case_id), None)
        closed = bool(state and state["completed"])
        score = state["score"] if state else 0

        case_selector = "".join(
            f'<p><strong>{escape(c["title"])}</strong> '
            f'<small>(Difficulty {escape(str(c["difficulty"]))} — '
            f'{"Completed" if c["completed"] else ("Unlocked" if c["unlocked"] else "Locked")})</small>'
            + (
                f' <a href="/?case={escape(c["case_id"])}">Open case</a>'
                if c["unlocked"] and c["case_id"] != case_id
                else ""
            )
            + "</p>"
            for c in all_cases
        )

        try:
            case = engine.get_case_details(PLAYER, case_id)
        except PermissionError as exc:
            fallback_meta = next((c for c in all_cases if c["case_id"] == case_id), None)
            notice = f'<p class="notice" role="status">{escape(str(exc))}</p>'
            template = Template((ROOT / "frontend/demo.html").read_text(encoding="utf-8"))
            body = template.substitute(
                title=escape(fallback_meta["title"] if fallback_meta else case_id),
                briefing=escape(str(exc)),
                score=score,
                notice=notice,
                evidence=f"<article><h2>Investigation cases</h2>{case_selector}</article>",
                actions="<p>Complete the prerequisite case first to unlock this investigation.</p>",
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        evidence = [f"<article><h2>Investigation cases</h2>{case_selector}</article>"]
        for item in case["evidence"]:
            item_id = item["evidence_id"]
            flag = ""
            if state and item_id in state["flagged_evidence"]:
                flag = '<span class="marked">Flagged as a clue</span>'
            elif state and not closed:
                flag = self.form(
                    "flag",
                    f'<input type="hidden" name="case_id" value="{escape(case_id)}">'
                    f'<input type="hidden" name="id" value="{escape(item_id)}">',
                    "Flag as a clue",
                )
            evidence.append(
                f'<article><small>{escape(item["type"].replace("_", " "))}</small>'
                f'<h3>{escape(item["title"])}</h3><pre>{escape(item["content"])}</pre>{flag}</article>'
            )

        actions = ""
        if state:
            notes = "".join(
                f'<li>{escape(n["note"])} <small>({escape(n["evidence_id"])})</small></li>'
                for n in state["notebook"]
            )
            actions = "<h2>Investigation notebook</h2>"
            if notes:
                actions += f"<ul>{notes}</ul>"
            if not closed:
                items = "".join(
                    f'<option value="{escape(i["evidence_id"])}">{escape(i["title"])}</option>'
                    for i in case["evidence"]
                )
                actions += self.form(
                    "note",
                    f'<input type="hidden" name="case_id" value="{escape(case_id)}">'
                    f'<label>Evidence<select name="id">{items}</select></label>'
                    '<label>Observation<textarea name="note" required></textarea></label>',
                    "Save note",
                )
                actions += self.form(
                    "hint",
                    f'<input type="hidden" name="case_id" value="{escape(case_id)}">',
                    "Request next hint",
                )
                for idx, decision in enumerate(case["decisions"]):
                    choices = "".join(
                        f'<label class="choice"><input type="radio" required name="choice" value="{i}">'
                        f"{escape(label)}</label>"
                        for i, label in enumerate(decision["options"])
                    )
                    actions += f"<h2>Decision {idx + 1}</h2>" + self.form(
                        "decision",
                        f'<input type="hidden" name="case_id" value="{escape(case_id)}">'
                        f'<input type="hidden" name="decision_id" value="{escape(decision["decision_id"])}">'
                        f'<fieldset><legend>{escape(decision["prompt"])}</legend>{choices}</fieldset>',
                        "Submit decision",
                    )
                actions += "<h2>Conclusion</h2>" + self.form(
                    "complete",
                    f'<input type="hidden" name="case_id" value="{escape(case_id)}">'
                    f'<label>{escape(case["conclusion_prompt"])}'
                    '<textarea name="conclusion" required></textarea></label>',
                    "Close case",
                )
            else:
                actions += (
                    "<p>Investigation complete. Your score and notes are saved.</p>"
                    + self.form(
                        "start",
                        f'<input type="hidden" name="case_id" value="{escape(case_id)}">',
                        "Play again",
                    )
                )
        else:
            actions = (
                "<h2>Investigation objectives</h2><ul>"
                + "".join(f"<li>{escape(o)}</li>" for o in case["learning_objectives"])
                + "</ul>"
                + self.form(
                    "start",
                    f'<input type="hidden" name="case_id" value="{escape(case_id)}">',
                    "Start investigation",
                )
            )

        notice = (
            f'<p class="notice" role="status">{escape(self.server.notice)}</p>'
            if self.server.notice
            else ""
        )
        template = Template((ROOT / "frontend/demo.html").read_text(encoding="utf-8"))
        body = template.substitute(
            title=escape(case["title"]),
            briefing=escape(case["briefing"]),
            score=score,
            notice=notice,
            evidence="".join(evidence),
            actions=actions,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.headers.get("Host") != self.server.address:
            self.send_error(403)
            return
        size = self.headers.get("Content-Length", "")
        if not size.isdecimal() or int(size) > 65536:
            self.send_error(413)
            return
        fields = {k: v[0] for k, v in parse_qs(self.rfile.read(int(size)).decode()).items()}
        if fields.get("token") != self.server.token:
            self.send_error(403)
            return

        engine = self.server.engine
        case_id = self._current_case_id(fields.get("case_id"))
        try:
            if self.path == "/start":
                engine.start_case(PLAYER, case_id)
                message = "Investigation opened."
            elif self.path == "/flag":
                engine.flag_evidence(PLAYER, case_id, fields["id"])
                message = "Evidence flagged."
            elif self.path == "/note":
                engine.add_notebook_entry(PLAYER, case_id, fields["id"], fields["note"])
                message = "Observation saved."
            elif self.path == "/hint":
                hint = engine.request_hint(PLAYER, case_id)
                message = f'Hint {hint["level"]} (cost: {hint["cost"]} points). {hint["text"]}'
            elif self.path == "/decision":
                details = engine.get_case_details(PLAYER, case_id)
                target_id = fields.get("decision_id")
                decision = next(
                    (d for d in details["decisions"] if d["decision_id"] == target_id),
                    details["decisions"][0],
                )
                result = engine.evaluate_decision(
                    PLAYER, case_id, decision["decision_id"], int(fields["choice"])
                )
                message = result["feedback"]
            elif self.path == "/complete":
                completion = engine.complete_case(PLAYER, case_id, fields["conclusion"])
                if completion["completed"] and completion.get("unlocked_cases"):
                    unlocked_names = ", ".join(completion["unlocked_cases"])
                    message = f'{completion["feedback"]} Unlocked: {unlocked_names}.'
                else:
                    message = completion["feedback"]
            else:
                self.send_error(404)
                return
        except (LookupError, ValueError, PermissionError, KeyError) as exc:
            message = str(exc)

        self.server.notice = message
        self.send_response(303)
        self.send_header("Location", f"/?case={case_id}")
        self.end_headers()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
        / "CyberDetectiveDemo",
    )
    args = parser.parse_args()
    engine = GameEngine(ROOT / "cases", args.data_dir / "progress.db")
    with HTTPServer(("127.0.0.1", args.port), Demo) as server:
        server.engine = engine
        server.notice = ""
        server.token = secrets.token_urlsafe(24)
        server.address = f"127.0.0.1:{server.server_port}"
        url = f"http://{server.address}/"
        print(url, flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        server.serve_forever()


if __name__ == "__main__":
    main()