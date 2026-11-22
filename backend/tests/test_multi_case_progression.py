from pathlib import Path
import pytest

from app.engine import GameEngine


CASES_DIR = Path(__file__).resolve().parents[2] / "cases"


def _solve_case(engine: GameEngine, player_id: str, case_id: str, conclusion_text: str) -> dict:
    details = engine.get_case_details(player_id, case_id)
    engine.start_case(player_id, case_id)
    for item in details["evidence"]:
        engine.flag_evidence(player_id, case_id, item["evidence_id"])
    for decision in details["decisions"]:
        for idx in range(len(decision["options"])):
            res = engine.evaluate_decision(player_id, case_id, decision["decision_id"], idx)
            if res["is_correct"]:
                break
    return engine.complete_case(player_id, case_id, conclusion_text)


def test_sequential_unlock_across_three_shipped_cases(tmp_path: Path):
    db_path = tmp_path / "progression.db"
    engine = GameEngine(cases_dir=CASES_DIR, db_path=db_path)
    player = "student_multi"

    initial_listing = {item["case_id"]: item for item in engine.list_cases(player)}
    assert initial_listing["suspicious_email"]["unlocked"] is True
    assert initial_listing["midnight_login"]["unlocked"] is False
    assert initial_listing["compromised_workstation"]["unlocked"] is False

    with pytest.raises(PermissionError):
        engine.start_case(player, "midnight_login")
    with pytest.raises(PermissionError):
        engine.start_case(player, "compromised_workstation")

    c1_result = _solve_case(
        engine,
        player,
        "suspicious_email",
        "This is phishing: do not click the link and report it to security.",
    )
    assert c1_result["completed"] is True
    assert "midnight_login" in c1_result["unlocked_cases"]

    after_c1 = {item["case_id"]: item for item in engine.list_cases(player)}
    assert after_c1["suspicious_email"]["completed"] is True
    assert after_c1["midnight_login"]["unlocked"] is True
    assert after_c1["compromised_workstation"]["unlocked"] is False

    c2_result = _solve_case(
        engine,
        player,
        "midnight_login",
        "Suspicious login from an external ip after failed attempts; reset the password.",
    )
    assert c2_result["completed"] is True
    assert "compromised_workstation" in c2_result["unlocked_cases"]

    c3_result = _solve_case(
        engine,
        player,
        "compromised_workstation",
        "Found a suspicious process and outbound connection; isolate the host.",
    )
    assert c3_result["completed"] is True


def test_invalid_decision_option_and_replay_preserves_best_score(tmp_path: Path):
    db_path = tmp_path / "replay.db"
    engine = GameEngine(cases_dir=CASES_DIR, db_path=db_path)
    player = "student_replay"

    engine.start_case(player, "suspicious_email")
    with pytest.raises(ValueError, match="valid option index"):
        engine.evaluate_decision(player, "suspicious_email", "dec_01", 99)

    first_run = _solve_case(
        engine,
        player,
        "suspicious_email",
        "Phishing link detected; report it immediately.",
    )
    assert first_run["completed"] is True
    best_score = first_run["score"]

    repeat_complete = engine.complete_case(
        player,
        "suspicious_email",
        "Phishing link detected; report it immediately.",
    )
    assert repeat_complete == first_run

    restarted = engine.start_case(player, "suspicious_email")
    assert restarted["completed"] is False
    assert restarted["score"] == 0
    assert restarted["flagged_evidence"] == []
    assert restarted["notebook"] == []
    assert restarted["hint_count"] == 0

    progress = engine.get_player_progress(player)
    assert progress["completed_cases"]["suspicious_email"] == best_score