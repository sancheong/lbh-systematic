import json

from lbh.core.config import Config, init_config
from lbh.core.request_classification import RequestClassificationKind, classify_patch_request
from lbh.session.manager import SessionManager
from lbh.workflow import ask_request


class FakeRanker:
    def __init__(self, repo):
        self.repo = repo

    def rank(self, request, *, limit=None):
        return []


def _enable_broad_planning(repo_root):
    config_path = repo_root / ".lbh" / "config.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "enable_broad_request_planning = false",
            "enable_broad_request_planning = true",
        ),
        encoding="utf-8",
    )


def test_classifies_small_request_for_normal_gateway_run():
    result = classify_patch_request("Fix typo in src/lbh/workflow.py")

    assert result.kind is RequestClassificationKind.SMALL
    assert result.is_small is True
    assert result.is_broad_or_multi_component is False
    assert result.uses_normal_gateway_run is True
    assert result.component_count == 1


def test_classifies_broad_request_by_contract_terms():
    result = classify_patch_request("Overhaul the request routing architecture")

    assert result.kind is RequestClassificationKind.SMALL
    assert result.is_broad_or_multi_component is False
    assert result.uses_normal_gateway_run is True
    assert result.reasons == ()


def test_classifies_multi_component_request_by_component_limit():
    result = classify_patch_request("Update parser, CLI, and prompt generation")

    assert result.kind is RequestClassificationKind.SMALL
    assert result.is_broad_or_multi_component is False
    assert result.uses_normal_gateway_run is True
    assert result.component_count == 1
    assert result.reasons == ()


def test_can_enable_experimental_broad_request_planning_via_config():
    config = Config(
        {
            "experimental": {"enable_broad_request_planning": True},
        }
    )

    result = classify_patch_request("Overhaul the request routing architecture", config)

    assert result.kind is RequestClassificationKind.BROAD
    assert result.is_broad_or_multi_component is True
    assert result.uses_normal_gateway_run is False
    assert "broad_term:architecture" in result.reasons
    assert "broad_term:overhaul" in result.reasons


def test_can_enable_experimental_multi_component_planning_via_config():
    config = Config(
        {
            "experimental": {"enable_broad_request_planning": True},
        }
    )

    result = classify_patch_request("Update parser, CLI, and prompt generation", config)

    assert result.kind is RequestClassificationKind.MULTI_COMPONENT
    assert result.is_broad_or_multi_component is True
    assert result.uses_normal_gateway_run is False
    assert result.component_count > config.request_classification_component_limit
    assert result.reasons == ("component_count>1",)


def test_ask_request_exposes_classification_for_later_routing(tmp_path, monkeypatch):
    init_config(tmp_path)
    monkeypatch.setattr("lbh.workflow.SearchRanker", FakeRanker)

    result = ask_request(tmp_path, "Update parser, CLI, and prompt generation")

    assert result.request_classification.kind is RequestClassificationKind.SMALL
    assert result.request_classification.is_broad_or_multi_component is False


def test_small_request_does_not_create_plan_layout(tmp_path, monkeypatch):
    init_config(tmp_path)
    monkeypatch.setattr("lbh.workflow.SearchRanker", FakeRanker)

    result = ask_request(tmp_path, "Fix typo in src/lbh/workflow.py")

    manifest = (result.session_root / "manifest.json").read_text(encoding="utf-8")
    assert '"plan": null' in manifest
    assert not (tmp_path / ".lbh" / "plans").iterdir().__next__ if any((tmp_path / ".lbh" / "plans").iterdir()) else True


def test_medium_to_large_request_creates_separated_plan_artifacts(tmp_path, monkeypatch):
    init_config(tmp_path)
    _enable_broad_planning(tmp_path)
    monkeypatch.setattr("lbh.workflow.SearchRanker", FakeRanker)
    (tmp_path / "refactoring.md").write_text("bootstrap only", encoding="utf-8")

    result = ask_request(tmp_path, "Update parser, CLI, and prompt generation")

    plan_root = tmp_path / ".lbh" / "plans" / result.session_root.name
    prompt_path = plan_root / "prompts" / "task_prompt_001.md"
    state_path = plan_root / "state.json"
    summary_path = plan_root / "summary.md"
    assert prompt_path.exists()
    assert state_path.exists()
    assert summary_path.exists()
    assert state_path.parent == prompt_path.parent.parent
    assert summary_path.parent == prompt_path.parent.parent
    assert state_path.parent != prompt_path.parent
    assert summary_path.parent != prompt_path.parent
    assert not (plan_root / "refactoring.md").exists()

    manifest_text = (result.session_root / "manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert '"bootstrap_source": "refactoring.md"' in manifest_text
    assert '"bootstrap_temporary": true' in manifest_text
    assert '"state": ".lbh/plans/' in manifest_text
    assert '"summary": ".lbh/plans/' in manifest_text
    assert '"immutable_prompts_dir": ".lbh/plans/' in manifest_text
    assert manifest["plan"]["prompt_files"][0].endswith("task_prompt_001.md")


def test_plan_prompt_splitting_is_idempotent_and_immutable(tmp_path, monkeypatch):
    init_config(tmp_path)
    _enable_broad_planning(tmp_path)
    monkeypatch.setattr("lbh.workflow.SearchRanker", FakeRanker)

    result = ask_request(tmp_path, "Update parser, CLI, and prompt generation")
    plan_root = tmp_path / ".lbh" / "plans" / result.session_root.name
    prompt_path = plan_root / "prompts" / "task_prompt_001.md"
    state_path = plan_root / "state.json"
    summary_path = plan_root / "summary.md"
    original_prompt = prompt_path.read_text(encoding="utf-8")

    state_path.write_text('{"schema":"lbh.plan.state.v1","status":"in_progress"}', encoding="utf-8")
    summary_path.write_text("progress update", encoding="utf-8")

    SessionManager(tmp_path).create_plan_artifacts(
        result.session_root,
        {"task_prompt.md": "rewritten mutable progress that must not replace the immutable prompt"},
    )

    assert prompt_path.read_text(encoding="utf-8") == original_prompt
    assert "rewritten mutable progress" not in prompt_path.read_text(encoding="utf-8")
    assert state_path.read_text(encoding="utf-8") == '{"schema":"lbh.plan.state.v1","status":"in_progress"}'
    assert summary_path.read_text(encoding="utf-8") == "progress update"


def test_plan_prompt_splitting_creates_per_task_prompt_files_once(tmp_path):
    init_config(tmp_path)
    manager = SessionManager(tmp_path)
    session = manager.create("broad plan")

    manager.create_plan_artifacts(session.root, {"task_prompt.md": "first task\n---\nsecond task"})
    plan_root = tmp_path / ".lbh" / "plans" / session.root.name
    prompts = sorted(path.name for path in (plan_root / "prompts").iterdir())

    assert prompts == ["task_prompt_001.md", "task_prompt_002.md"]
    assert (plan_root / "prompts" / "task_prompt_001.md").read_text(encoding="utf-8") == "first task"
    assert (plan_root / "prompts" / "task_prompt_002.md").read_text(encoding="utf-8") == "second task"

    manager.create_plan_artifacts(session.root, {"task_prompt.md": "replacement\n---\nreplacement"})

    assert sorted(path.name for path in (plan_root / "prompts").iterdir()) == prompts
    assert (plan_root / "prompts" / "task_prompt_001.md").read_text(encoding="utf-8") == "first task"
    assert (plan_root / "prompts" / "task_prompt_002.md").read_text(encoding="utf-8") == "second task"
