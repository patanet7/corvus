"""Behavioral tests for hierarchical task planning and route model selection."""

from pathlib import Path

from corvus.gateway.task_planner import TaskPlanner
from corvus.model_router import ModelRouter


def _build_planner() -> tuple[TaskPlanner, ModelRouter]:
    model_router = ModelRouter.from_file(Path("config/models.yaml"))
    planner = TaskPlanner.from_file(
        Path("config/task_routing.yaml"),
        model_router=model_router,
    )
    return planner, model_router


class TestTaskPlanner:
    """Validates decomposition, model routing, and fallback strategy contracts."""

    def test_decomposes_coding_message_with_skill_models(self):
        planner, model_router = _build_planner()
        plan = planner.plan(
            message="Please refactor the backend API and implement tests.",
            requested_agents=["general"],
            enabled_agents=["work", "docs", "finance", "general"],
            requested_model=None,
            user_forced_agents=False,
        )
        assert plan.task_type == "coding"
        assert plan.decomposed is True
        assert len(plan.routes) >= 2
        assert all(route.task_type == "coding" for route in plan.routes)
        for route in plan.routes:
            if route.skill and route.skill in model_router.list_skills():
                assert route.requested_model == model_router.get_skill_model(route.skill)

    def test_forced_agents_limit_decomposition_targets(self):
        planner, _ = _build_planner()
        plan = planner.plan(
            message="Refactor the backend and add a rollout summary.",
            requested_agents=["work"],
            enabled_agents=["work", "docs", "general"],
            requested_model=None,
            user_forced_agents=True,
        )
        assert plan.decomposed is True
        assert len(plan.routes) >= 1
        assert all(route.agent == "work" for route in plan.routes)

    def test_requested_model_overrides_skill_model(self):
        planner, _ = _build_planner()
        plan = planner.plan(
            message="Implement backend API refactor and test coverage.",
            requested_agents=["work"],
            enabled_agents=["work", "docs", "general"],
            requested_model="opus",
            user_forced_agents=False,
        )
        assert len(plan.routes) >= 1
        assert all(route.requested_model == "opus" for route in plan.routes)

    def test_non_matching_message_falls_back_to_direct_routes(self):
        planner, _ = _build_planner()
        plan = planner.plan(
            message="hello team",
            requested_agents=["work", "docs"],
            enabled_agents=["work", "docs", "general"],
            requested_model=None,
            user_forced_agents=True,
        )
        assert plan.decomposed is False
        assert plan.strategy == "parallel"
        assert [route.agent for route in plan.routes] == ["work", "docs"]
        assert all(route.prompt == "hello team" for route in plan.routes)

    def test_no_enabled_agents_returns_empty_plan(self):
        planner, _ = _build_planner()
        plan = planner.plan(
            message="refactor backend",
            requested_agents=["work"],
            enabled_agents=[],
            requested_model=None,
            user_forced_agents=False,
        )
        assert plan.routes == []
        assert plan.decomposed is False
        assert plan.strategy == "direct"
        assert plan.rationale == "No enabled agents available."
