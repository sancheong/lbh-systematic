from lbh.core.models import CandidateIssue, CandidateValidation
from lbh.patch.candidate import render_repair_prompt


def test_render_repair_prompt_prefers_hashline_mode():
    validation = CandidateValidation(
        candidate="candidates/candidate_001.diff",
        ok=False,
        source_mode="hashline",
        errors=[CandidateIssue(kind="apply_check_failed", message="git apply --check failed.")],
        repair_instruction=[
            "Revise the candidate patch only. Do not redesign the feature.",
            "Make the deterministic materialized diff pass `git apply --check`.",
            "Preserve correct parts of the candidate.",
            "Produce exactly one fenced `lbh-hashline-patch` block.",
        ],
    )

    prompt = render_repair_prompt(validation)
    assert "`lbh-hashline-patch`" in prompt
    assert "Do not fall back to a unified diff response." in prompt
    assert "Produce exactly one fenced `lbh-hashline-patch` block." in prompt
    assert "Produce a valid git unified diff." not in prompt


def test_candidate_validation_to_dict_includes_source_mode():
    validation = CandidateValidation(candidate="candidates/candidate_001.diff", ok=False, source_mode="hashline")
    data = validation.to_dict()
    assert data["source_mode"] == "hashline"
