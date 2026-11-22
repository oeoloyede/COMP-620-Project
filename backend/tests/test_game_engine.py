from pathlib import Path
import json
import pytest

# Adjust this import to match your backend engine module/class name
# Example expected interface:
#   engine = GameEngine(cases_dir=..., db_path=...)
#   state = engine.start_case(player_id, case_id)
#   state = engine.flag_evidence(player_id, case_id, evidence_id)
#   state = engine.add_notebook_entry(player_id, case_id, evidence_id, note)
#   result = engine.evaluate_decision(player_id, case_id, decision_id, option_id)
#   hint = engine.request_hint(player_id, case_id)
#   summary = engine.complete_case(player_id, case_id, conclusion_text)
from app.engine import GameEngine  # type: ignore[import-not-found]


@pytest.fixture()
def sample_cases_dir(tmp_path: Path) -> Path:
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()

    case_1 = {
        "case_id": "suspicious_email",
        "title": "The Suspicious Email",
        "difficulty": "Beginner",
        "unlock_requirement": None,
        "completion_bonus": 25,
        "evidence": [
            {
                "evidence_id": "ev_email_01",
                "type": "email",
                "is_key_clue": True,
                "points": 20,
            },
            {
                "evidence_id": "ev_distractor_01",
                "type": "employee_record",
                "is_key_clue": False,
                "points": 0,
            },
        ],
        "decisions": [
            {
                "decision_id": "dec_phishing",
                "correct_option_id": "opt_quarantine",
                "points": 40,
                "penalty": 15,
                "feedback_correct": "Lookalike domain and urgent request indicate phishing.",
                "feedback_incorrect": "Check sender domain and link destination again.",
            }
        ],
        "hints": [
            {"level": 1, "type": "general_direction", "cost": 5, "text": "Check sender and links."},
            {"level": 2, "type": "evidence_category", "cost": 10, "text": "Inspect email items."},
            {"level": 3, "type": "specific_evidence", "cost": 15, "text": "Examine ev_email_01."},
            {"level": 4, "type": "concept_explanation", "cost": 15, "text": "Phishing uses urgency and spoofing."},
        ],
        "conclusion": {
            "required_keywords": ["phishing", "lookalike"],
            "points": 45,
        },
    }

    case_2 = {
        "case_id": "midnight_login",
        "title": "The Midnight Login",
        "difficulty": "Intermediate",
        "unlock_requirement": "suspicious_email",
        "completion_bonus": 30,
        "evidence": [],
        "decisions": [],
        "hints": [],
        "conclusion": {
            "required_keywords": ["brute", "ip"],
            "points": 50,
        },
    }

    (cases_dir / "suspicious_email.json").write_text(json.dumps(case_1), encoding="utf-8")
    (cases_dir / "midnight_login.json").write_text(json.dumps(case_2), encoding="utf-8")
    return cases_dir


@pytest.fixture()
def engine(sample_cases_dir: Path, tmp_path: Path) -> GameEngine:
    db_path = tmp_path / "test_cyber_detective.db"
    return GameEngine(cases_dir=sample_cases_dir, db_path=db_path)


def test_start_case_resets_session_and_blocks_locked_case(engine: GameEngine):
    # Locked case should not start before prerequisite completion
    with pytest.raises(PermissionError):
        engine.start_case(player_id="player_1", case_id="midnight_login")

    state = engine.start_case(player_id="player_1", case_id="suspicious_email")
    assert state["score"] == 0
    assert state["flagged_evidence"] == []
    assert state["notebook"] == []


def test_evidence_flagging_awards_key_clue_points_once(engine: GameEngine):
    engine.start_case(player_id="player_1", case_id="suspicious_email")

    first_flag = engine.flag_evidence(player_id="player_1", case_id="suspicious_email", evidence_id="ev_email_01")
    assert first_flag["score"] == 20

    # Flagging the same clue again should not double-award points
    duplicate_flag = engine.flag_evidence(player_id="player_1", case_id="suspicious_email", evidence_id="ev_email_01")
    assert duplicate_flag["score"] == 20

    # Distractor evidence should award 0 points
    distractor_flag = engine.flag_evidence(
        player_id="player_1", case_id="suspicious_email", evidence_id="ev_distractor_01"
    )
    assert distractor_flag["score"] == 20


def test_notebook_persists_entry_linked_to_evidence(engine: GameEngine):
    engine.start_case(player_id="player_1", case_id="suspicious_email")
    state = engine.add_notebook_entry(
        player_id="player_1",
        case_id="suspicious_email",
        evidence_id="ev_email_01",
        note="Domain uses 'acm3' instead of 'acme'.",
    )
    assert len(state["notebook"]) == 1
    entry = state["notebook"][0]
    assert entry["evidence_id"] == "ev_email_01"
    assert "acm3" in entry["note"]


def test_evaluate_decision_correct_and_incorrect_paths(engine: GameEngine):
    engine.start_case(player_id="player_1", case_id="suspicious_email")

    wrong = engine.evaluate_decision(
        player_id="player_1",
        case_id="suspicious_email",
        decision_id="dec_phishing",
        option_id="opt_ignore",
    )
    assert wrong["is_correct"] is False
    assert wrong["score"] == -15
    assert len(wrong["feedback"]) > 0

    right = engine.evaluate_decision(
        player_id="player_1",
        case_id="suspicious_email",
        decision_id="dec_phishing",
        option_id="opt_quarantine",
    )
    assert right["is_correct"] is True
    assert right["score"] == 25  # -15 + 40
    assert len(right["feedback"]) > 0


def test_progressive_hints_deduct_cost_in_order(engine: GameEngine):
    engine.start_case(player_id="player_1", case_id="suspicious_email")

    h1 = engine.request_hint(player_id="player_1", case_id="suspicious_email")
    assert h1["level"] == 1
    assert h1["score"] == -5

    h2 = engine.request_hint(player_id="player_1", case_id="suspicious_email")
    assert h2["level"] == 2
    assert h2["score"] == -15  # -5 - 10

    h3 = engine.request_hint(player_id="player_1", case_id="suspicious_email")
    assert h3["level"] == 3
    assert h3["score"] == -30  # -15 - 15

    h4 = engine.request_hint(player_id="player_1", case_id="suspicious_email")
    assert h4["level"] == 4
    assert h4["score"] == -45  # -30 - 15


def test_complete_case_awards_bonus_and_unlocks_next_case(engine: GameEngine, tmp_path: Path):
    engine.start_case(player_id="player_1", case_id="suspicious_email")
    engine.flag_evidence(player_id="player_1", case_id="suspicious_email", evidence_id="ev_email_01")
    engine.evaluate_decision(
        player_id="player_1",
        case_id="suspicious_email",
        decision_id="dec_phishing",
        option_id="opt_quarantine",
    )

    result = engine.complete_case(
        player_id="player_1",
        case_id="suspicious_email",
        conclusion_text="This is a phishing attempt using a lookalike domain.",
    )
    # 20 (clue) + 40 (decision) + 45 (conclusion) + 25 (completion bonus) = 130
    assert result["score"] == 130
    assert "midnight_login" in result["unlocked_cases"]

    # Verify persistence across a new GameEngine instance reading the same SQLite DB
    reloaded = GameEngine(cases_dir=engine.cases_dir, db_path=engine.db_path)
    next_state = reloaded.start_case(player_id="player_1", case_id="midnight_login")
    assert next_state["case_id"] == "midnight_login"


def test_case_order_and_completion_require_the_investigation_decision(engine: GameEngine):
    player = "student"
    first = "suspicious_email"
    second = "midnight_login"
    conclusion = "This is phishing using a lookalike domain."
    assert [case["case_id"] for case in engine.list_cases(player)] == [first, second]
    engine.start_case(player, first)
    assert engine.complete_case(player, first, conclusion)["completed"] is False
    engine.evaluate_decision(player, first, "dec_phishing", "opt_ignore")
    assert engine.complete_case(player, first, conclusion)["completed"] is False
    with pytest.raises(PermissionError):
        engine.get_case_details(player, second)
    engine.evaluate_decision(player, first, "dec_phishing", "opt_quarantine")
    with pytest.raises(ValueError, match="already been solved"):
        engine.evaluate_decision(player, first, "dec_phishing", "opt_ignore")
    summary = engine.complete_case(player, first, conclusion)
    assert summary["unlocked_cases"] == [second]
    assert summary["score"] == 95
