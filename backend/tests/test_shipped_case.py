from pathlib import Path

from app.engine import GameEngine


def test_shipped_phishing_case_can_be_played_offline_and_reloaded(tmp_path):
    cases_dir = Path(__file__).resolve().parents[2] / "cases"
    db_path = tmp_path / "progress.db"
    engine = GameEngine(cases_dir, db_path)
    player_id = "student"
    case_id = "suspicious_email"

    listing = engine.list_cases(player_id)
    assert any(case["case_id"] == case_id and case["unlocked"] for case in listing)

    details = engine.get_case_details(player_id, case_id)
    assert "is_key_clue" not in details["evidence"][0]
    assert "correct_option_index" not in details["decisions"][0]

    engine.start_case(player_id, case_id)
    engine.flag_evidence(player_id, case_id, "ev_email_01")
    engine.flag_evidence(player_id, case_id, "ev_header_02")
    engine.add_notebook_entry(player_id, case_id, "ev_header_02", "The SPF check failed.")
    assert engine.request_hint(player_id, case_id)["level"] == 1
    assert engine.evaluate_decision(player_id, case_id, "dec_01", 0)["score"] == 15
    assert engine.evaluate_decision(player_id, case_id, "dec_01", 0)["score"] == 15
    assert engine.evaluate_decision(player_id, case_id, "dec_01", 1)["score"] == 35
    assert engine.evaluate_decision(player_id, case_id, "dec_01", 1)["score"] == 35

    incomplete = engine.complete_case(player_id, case_id, "The email looks suspicious.")
    assert incomplete["completed"] is False
    assert incomplete["score"] == 35

    conclusion = "This is phishing. Avoid the link and report the email to IT."
    completed = engine.complete_case(player_id, case_id, conclusion)
    assert completed["completed"] is True
    assert completed["score"] == 60

    reloaded = GameEngine(cases_dir, db_path)
    assert reloaded.complete_case(player_id, case_id, conclusion) == completed
    progress = reloaded.get_player_progress(player_id)
    assert progress["completed_cases"] == {case_id: 60}
    assert progress["investigations"][0]["notebook"] == [
        {"evidence_id": "ev_header_02", "note": "The SPF check failed."}
    ]
    assert reloaded.get_player_progress("other_student")["investigations"] == []
