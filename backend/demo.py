"""Local browser preview of the shipped Cyber Detective case."""
import argparse
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import os
import secrets
from string import Template
from urllib.parse import parse_qs
import webbrowser

from .app.engine import GameEngine

ROOT = Path(__file__).resolve().parents[1]
CASE = "suspicious_email"
PLAYER = "local-demo"


class Demo(BaseHTTPRequestHandler):
    def form(self, action, fields, label):
        return (f'<form method="post" action="/{action}">'
                f'<input type="hidden" name="token" value="{self.server.token}">'
                f'{fields}<button>{escape(label)}</button></form>')

    def do_GET(self):
        if self.headers.get("Host") != self.server.address or self.path != "/":
            self.send_error(404)
            return
        engine = self.server.engine
        case = engine.get_case_details(PLAYER, CASE)
        progress = engine.get_player_progress(PLAYER)["investigations"]
        state = next((entry for entry in progress if entry["case_id"] == CASE), None)
        closed = state and state["completed"]
        score = state["score"] if state else 0
        evidence = []
        for item in case["evidence"]:
            item_id = item["evidence_id"]
            flag = ""
            if state and item_id in state["flagged_evidence"]:
                flag = '<span class="marked">Flagged as a clue</span>'
            elif state and not closed:
                flag = self.form("flag", f'<input type="hidden" name="id" value="{escape(item_id)}">', "Flag as a clue")
            evidence.append(f'<article><small>{escape(item["type"].replace("_", " "))}</small>'
                            f'<h3>{escape(item["title"])}</h3><pre>{escape(item["content"])}</pre>{flag}</article>')
        actions = ""
        if state:
            notes = "".join(f'<li>{escape(n["note"])} <small>({escape(n["evidence_id"])})</small></li>'
                            for n in state["notebook"])
            actions = '<h2>Investigation notebook</h2>'
            if notes:
                actions += f'<ul>{notes}</ul>'
            if not closed:
                items = "".join(f'<option value="{escape(i["evidence_id"])}">{escape(i["title"])}</option>'
                                for i in case["evidence"])
                actions += self.form("note", f'<label>Evidence<select name="id">{items}</select></label>'
                                     '<label>Observation<textarea name="note" required></textarea></label>', "Save note")
                actions += self.form("hint", "", "Request next hint")
                decision = case["decisions"][0]
                choices = "".join(f'<label class="choice"><input type="radio" required name="choice" value="{i}">'
                                  f'{escape(label)}</label>' for i, label in enumerate(decision["options"]))
                actions += '<h2>Decision</h2>' + self.form("decision", f'<fieldset><legend>{escape(decision["prompt"])}</legend>{choices}</fieldset>', "Submit decision")
                actions += '<h2>Conclusion</h2>' + self.form("complete", f'<label>{escape(case["conclusion_prompt"])}<textarea name="conclusion" required></textarea></label>', "Close case")
            else:
                actions += '<p>Investigation complete. Your score and notes are saved.</p>' + self.form("start", "", "Play again")
        else:
            actions = '<h2>Investigation objectives</h2><ul>' + "".join(f'<li>{escape(o)}</li>' for o in case["learning_objectives"]) + '</ul>' + self.form("start", "", "Start investigation")
        notice = f'<p class="notice" role="status">{escape(self.server.notice)}</p>' if self.server.notice else ""
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
        try:
            if self.path == "/start":
                engine.start_case(PLAYER, CASE)
                message = "Investigation opened."
            elif self.path == "/flag":
                engine.flag_evidence(PLAYER, CASE, fields["id"])
                message = "Evidence flagged."
            elif self.path == "/note":
                engine.add_notebook_entry(PLAYER, CASE, fields["id"], fields["note"])
                message = "Observation saved."
            elif self.path == "/hint":
                hint = engine.request_hint(PLAYER, CASE)
                message = f'Hint {hint["level"]} (cost: {hint["cost"]} points). {hint["text"]}'
            elif self.path == "/decision":
                decision = engine.get_case_details(PLAYER, CASE)["decisions"][0]
                message = engine.evaluate_decision(PLAYER, CASE, decision["decision_id"], int(fields["choice"]))["feedback"]
            elif self.path == "/complete":
                message = engine.complete_case(PLAYER, CASE, fields["conclusion"])["feedback"]
            else:
                self.send_error(404)
                return
        except (LookupError, ValueError, PermissionError) as exc:
            message = str(exc)
        self.server.notice = message
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "CyberDetectiveDemo")
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
