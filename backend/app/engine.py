"""Deterministic scoring and local progress storage for Cyber Detective."""

from collections.abc import Iterator
from contextlib import closing, contextmanager
from graphlib import TopologicalSorter
import json
from pathlib import Path
import re
import sqlite3


class GameEngine:
    def __init__(self, cases_dir: Path, db_path: Path):
        self.cases_dir = Path(cases_dir)
        self.db_path = Path(db_path)
        self._cases = {}
        for path in sorted(self.cases_dir.glob("*.json")):
            case = json.loads(path.read_text(encoding="utf-8"))
            case_id = case["case_id"]
            if case_id in self._cases:
                raise ValueError(f"Duplicate case ID: {case_id}")
            self._cases[case_id] = case

        # Keep prerequisite cases ahead of the cases they unlock in the case menu.
        prerequisites = TopologicalSorter()
        for case_id, case in self._cases.items():
            required = case.get("unlock_requirement")
            if required is None:
                prerequisites.add(case_id)
            elif required in self._cases:
                prerequisites.add(case_id, required)
            else:
                raise ValueError(f"{case_id} requires missing case {required}")
        self._case_order = tuple(prerequisites.static_order())

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._database(write=True) as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS investigations (
                    player_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    best_completed_score INTEGER,
                    PRIMARY KEY (player_id, case_id)
                )"""
            )

    @contextmanager
    def _database(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.row_factory = sqlite3.Row
            # Acquire the writer lock before reading so concurrent actions cannot lose updates.
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db

    def list_cases(self, player_id: str) -> list[dict]:
        with self._database() as db:
            scores = self._completed_scores(db, player_id)
        unlocked = set(self._unlocked_cases(scores))
        return [
            {
                "case_id": case_id,
                "title": self._cases[case_id]["title"],
                "difficulty": self._cases[case_id]["difficulty"],
                "unlocked": case_id in unlocked,
                "completed": case_id in scores,
            }
            for case_id in self._case_order
        ]

    def get_case_details(self, player_id: str, case_id: str) -> dict:
        case = self._cases[case_id]
        with self._database() as db:
            self._require_unlocked(case, self._completed_scores(db, player_id))
        return {
            "case_id": case_id,
            "title": case["title"],
            "briefing": case.get("briefing", ""),
            "learning_objectives": list(case.get("learning_objectives", [])),
            "evidence": [
                {
                    "evidence_id": item.get("evidence_id", item.get("id")),
                    "type": item["type"],
                    "title": item.get("title", ""),
                    "content": item.get("content", ""),
                }
                for item in case["evidence"]
            ],
            "decisions": [
                {
                    "decision_id": decision.get("decision_id", decision.get("id")),
                    "prompt": decision.get("prompt", ""),
                    "options": list(decision.get("options", [])),
                }
                for decision in case["decisions"]
            ],
            "conclusion_prompt": case["conclusion"].get("prompt", ""),
        }

    def get_player_progress(self, player_id: str) -> dict:
        with self._database() as db:
            rows = db.execute(
                """SELECT case_id, state, best_completed_score FROM investigations
                   WHERE player_id = ? ORDER BY case_id""",
                (player_id,),
            ).fetchall()
        return {
            "completed_cases": {
                row["case_id"]: row["best_completed_score"]
                for row in rows
                if row["best_completed_score"] is not None
            },
            "investigations": [self._player_state(json.loads(row["state"])) for row in rows],
        }

    def start_case(self, player_id: str, case_id: str) -> dict:
        case = self._cases[case_id]
        state = {
            "case_id": case_id,
            "score": 0,
            "flagged_evidence": [],
            "notebook": [],
            "hint_count": 0,
            "completed": False,
            "decision_attempts": {},
        }
        with self._database(write=True) as db:
            self._require_unlocked(case, self._completed_scores(db, player_id))
            db.execute(
                """INSERT INTO investigations (player_id, case_id, state) VALUES (?, ?, ?)
                   ON CONFLICT (player_id, case_id) DO UPDATE SET state = excluded.state""",
                (player_id, case_id, json.dumps(state)),
            )
        return self._player_state(state)

    def flag_evidence(self, player_id: str, case_id: str, evidence_id: str) -> dict:
        evidence = self._find_item(self._cases[case_id]["evidence"], "evidence_id", evidence_id)
        with self._active_investigation(player_id, case_id) as state:
            if evidence_id not in state["flagged_evidence"]:
                state["flagged_evidence"].append(evidence_id)
                if evidence["is_key_clue"]:
                    state["score"] += evidence["points"]
        return self._player_state(state)

    def add_notebook_entry(self, player_id: str, case_id: str, evidence_id: str, note: str) -> dict:
        self._find_item(self._cases[case_id]["evidence"], "evidence_id", evidence_id)
        note = note.strip()
        if not note:
            raise ValueError("A notebook entry must contain text.")
        with self._active_investigation(player_id, case_id) as state:
            state["notebook"].append({"evidence_id": evidence_id, "note": note})
        return self._player_state(state)

    def evaluate_decision(
        self, player_id: str, case_id: str, decision_id: str, option_id: str | int
    ) -> dict:
        decision = self._find_item(self._cases[case_id]["decisions"], "decision_id", decision_id)
        if "correct_option_index" in decision:
            correct_option = decision["correct_option_index"]
            if type(option_id) is not int or not 0 <= option_id < len(decision["options"]):
                raise ValueError("Choose a valid option index for this decision.")
        else:
            correct_option = decision["correct_option_id"]
            if not isinstance(option_id, str) or not option_id.strip():
                raise ValueError("Choose a valid option ID for this decision.")

        is_correct = option_id == correct_option
        with self._active_investigation(player_id, case_id) as state:
            attempts = state["decision_attempts"].setdefault(decision_id, [])
            if correct_option in attempts and not is_correct:
                raise ValueError("This decision has already been solved.")
            if option_id not in attempts:
                attempts.append(option_id)
                state["score"] += decision["points"] if is_correct else -decision["penalty"]
        return {
            "score": state["score"],
            "is_correct": is_correct,
            "feedback": decision["feedback_correct" if is_correct else "feedback_incorrect"],
        }

    def request_hint(self, player_id: str, case_id: str) -> dict:
        hints = sorted(self._cases[case_id]["hints"], key=lambda hint: hint["level"])
        with self._active_investigation(player_id, case_id) as state:
            if state["hint_count"] >= len(hints):
                raise LookupError("There are no more hints for this case.")
            hint = hints[state["hint_count"]]
            state["hint_count"] += 1
            state["score"] -= hint["cost"]
        return {**hint, "score": state["score"]}

    def complete_case(self, player_id: str, case_id: str, conclusion_text: str) -> dict:
        case = self._cases[case_id]
        with self._database(write=True) as db:
            state = self._load_state(db, player_id, case_id)
            if not state["completed"]:
                for decision in case["decisions"]:
                    decision_id = decision.get("decision_id", decision.get("id"))
                    correct = decision.get("correct_option_index", decision.get("correct_option_id"))
                    if correct not in state["decision_attempts"].get(decision_id, []):
                        return {
                            "completed": False,
                            "score": state["score"],
                            "feedback": "Resolve each investigation decision before closing the case.",
                            "unlocked_cases": [],
                        }
                if not self._valid_conclusion(case["conclusion"], conclusion_text):
                    return {
                        "completed": False,
                        "score": state["score"],
                        "feedback": "Explain what the evidence shows and what response you recommend.",
                        "unlocked_cases": [],
                    }

                scores = self._completed_scores(db, player_id)
                unlocked_before = set(self._unlocked_cases(scores))
                state["score"] += case["conclusion"]["points"] + case.get("completion_bonus", 0)
                state["completed"] = True
                scores[case_id] = max(scores.get(case_id, state["score"]), state["score"])
                state["unlocked_cases"] = [
                    candidate for candidate in self._unlocked_cases(scores)
                    if candidate not in unlocked_before
                ]
                db.execute(
                    """UPDATE investigations SET state = ?, best_completed_score = ?
                       WHERE player_id = ? AND case_id = ?""",
                    (json.dumps(state), scores[case_id], player_id, case_id),
                )
        return {
            "completed": True,
            "score": state["score"],
            "feedback": "Case completed.",
            "unlocked_cases": state["unlocked_cases"],
        }

    @contextmanager
    def _active_investigation(self, player_id: str, case_id: str) -> Iterator[dict]:
        with self._database(write=True) as db:
            state = self._load_state(db, player_id, case_id)
            if state["completed"]:
                raise PermissionError("This investigation is complete. Start a new attempt to replay it.")
            yield state
            db.execute(
                "UPDATE investigations SET state = ? WHERE player_id = ? AND case_id = ?",
                (json.dumps(state), player_id, case_id),
            )

    @staticmethod
    def _load_state(db: sqlite3.Connection, player_id: str, case_id: str) -> dict:
        row = db.execute(
            "SELECT state FROM investigations WHERE player_id = ? AND case_id = ?",
            (player_id, case_id),
        ).fetchone()
        if row is None:
            raise LookupError("Start this case before submitting an investigation action.")
        return json.loads(row["state"])

    @staticmethod
    def _player_state(state: dict) -> dict:
        return {key: value for key, value in state.items() if key != "decision_attempts"}

    @staticmethod
    def _completed_scores(db: sqlite3.Connection, player_id: str) -> dict[str, int]:
        return dict(db.execute(
            """SELECT case_id, best_completed_score FROM investigations
               WHERE player_id = ? AND best_completed_score IS NOT NULL""",
            (player_id,),
        ).fetchall())

    def _unlocked_cases(self, scores: dict[str, int]) -> list[str]:
        met_requirements = {None, *scores}
        return [
            case_id for case_id, case in self._cases.items()
            if case.get("unlock_requirement") in met_requirements
        ]

    @staticmethod
    def _require_unlocked(case: dict, scores: dict[str, int]) -> None:
        prerequisite = case.get("unlock_requirement")
        if prerequisite is not None and prerequisite not in scores:
            raise PermissionError(f"Complete {prerequisite} to unlock this case.")

    @staticmethod
    def _find_item(items: list[dict], id_field: str, item_id: str) -> dict:
        for item in items:
            if item.get(id_field, item.get("id")) == item_id:
                return item
        raise KeyError(item_id)

    @staticmethod
    def _valid_conclusion(conclusion: dict, text: str) -> bool:
        words = " ".join(re.findall(r"\w+", text.casefold()))
        if not words:
            return False
        return all(
            f" {keyword} " in f" {words} "
            for keyword in (
                " ".join(re.findall(r"\w+", phrase.casefold()))
                for phrase in conclusion["required_keywords"]
            )
        )
