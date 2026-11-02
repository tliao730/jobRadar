import re

import pytest

from job_radar.profile import AnswerRule, ProfileError, label_rule, load_profile


def test_missing_applicant_points_to_init_profile(tmp_path):
    with pytest.raises(ProfileError, match="init-profile"):
        load_profile(tmp_path)


def test_invalid_yaml_is_reported(tmp_path):
    (tmp_path / "applicant.yaml").write_text("basic: [unclosed", encoding="utf-8")
    with pytest.raises(ProfileError, match="YAML"):
        load_profile(tmp_path)


def test_highlights_file_is_optional(tmp_path):
    (tmp_path / "applicant.yaml").write_text("basic:\n  first_name: Jane\n", encoding="utf-8")
    profile = load_profile(tmp_path)
    assert profile.highlights == []
    assert profile.applicant.basic.first_name == "Jane"


def test_facts_leave_out_contact_details(profile):
    facts = profile.facts_for_llm(profile.resume_variants()["ds"])
    assert "Jane Doe" in facts
    assert "rec-ranking" in facts
    assert "University of Southern California" in facts
    assert "Built ranking models at Example Labs" in facts
    assert "jane@example.com" not in facts
    assert "555 0100" not in facts
    assert "[email]" in facts


def test_resume_variants(profile):
    assert list(profile.resume_variants()) == ["ds"]


def test_learned_answers_round_trip(profile, profile_dir):
    profile.save_learned(
        AnswerRule(match=label_rule("What is your  expected graduation date?"), answer="May 2026")
    )
    reloaded = load_profile(profile_dir)
    assert reloaded.learned[0].answer == "May 2026"
    assert reloaded.answer_rules()[0].matches("what is your expected graduation date?")
    assert not reloaded.answer_rules()[0].matches("What is your expected start date?")


def test_label_rule_is_a_full_match():
    rule = label_rule("Why Example Co?")
    assert re.search(rule, "  why   example co? ", re.I)
    assert not re.search(rule, "Why Example Co? Tell us more", re.I)
