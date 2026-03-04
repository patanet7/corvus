"""Task decomposition planner for multi-agent dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from corvus.model_router import ModelRouter


@dataclass(slots=True)
class TaskRoute:
    """One executable subtask route."""

    agent: str
    prompt: str
    requested_model: str | None
    task_type: str | None = None
    subtask_id: str | None = None
    skill: str | None = None
    instruction: str | None = None


@dataclass(slots=True)
class DispatchPlan:
    """Resolved execution plan for a user message."""

    task_type: str | None
    decomposed: bool
    strategy: str
    routes: list[TaskRoute]
    rationale: str

    @property
    def target_agents(self) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for route in self.routes:
            if route.agent in seen:
                continue
            seen.add(route.agent)
            ordered.append(route.agent)
        return ordered

    def to_payload(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "decomposed": self.decomposed,
            "strategy": self.strategy,
            "rationale": self.rationale,
            "routes": [
                {
                    "agent": route.agent,
                    "task_type": route.task_type,
                    "subtask_id": route.subtask_id,
                    "skill": route.skill,
                    "instruction": route.instruction,
                    "requested_model": route.requested_model,
                    "prompt_preview": route.prompt[:180],
                }
                for route in self.routes
            ],
        }


class TaskPlanner:
    """Builds per-subtask agent/model routing plans from config + prompt."""

    def __init__(self, config: dict[str, Any], model_router: ModelRouter) -> None:
        self._config = config
        self._model_router = model_router

    @classmethod
    def from_file(cls, path: Path, *, model_router: ModelRouter) -> TaskPlanner:
        if not path.exists():
            return cls({}, model_router=model_router)
        try:
            data = yaml.safe_load(path.read_text()) or {}
            if not isinstance(data, dict):
                data = {}
            return cls(data, model_router=model_router)
        except Exception:
            return cls({}, model_router=model_router)

    def plan(
        self,
        *,
        message: str,
        requested_agents: list[str],
        enabled_agents: list[str],
        requested_model: str | None,
        user_forced_agents: bool,
    ) -> DispatchPlan:
        """Return a dispatch plan with optional decomposition."""
        base_targets = self._dedupe([name for name in requested_agents if name in enabled_agents])
        if not base_targets:
            base_targets = enabled_agents[:1]
        if not base_targets:
            return DispatchPlan(
                task_type=None,
                decomposed=False,
                strategy="direct",
                routes=[],
                rationale="No enabled agents available.",
            )

        defaults = self._config.get("defaults", {})
        enable_decomposition = bool(defaults.get("enable_decomposition", True))
        expand_from_router = bool(defaults.get("expand_from_router", True))
        max_subtasks = max(1, int(defaults.get("max_subtasks", 6)))
        task_type = self._detect_task_type(message)

        if not enable_decomposition or task_type is None:
            return DispatchPlan(
                task_type=task_type,
                decomposed=False,
                strategy="parallel" if len(base_targets) > 1 else "direct",
                routes=[
                    TaskRoute(
                        agent=agent,
                        prompt=message,
                        requested_model=requested_model,
                        task_type=task_type,
                    )
                    for agent in base_targets
                ],
                rationale="No decomposition rule matched.",
            )

        task_cfg = self._config.get("task_types", {}).get(task_type, {})
        decomposition = task_cfg.get("decomposition", {})
        if not bool(decomposition.get("enabled", False)):
            return DispatchPlan(
                task_type=task_type,
                decomposed=False,
                strategy="parallel" if len(base_targets) > 1 else "direct",
                routes=[
                    TaskRoute(
                        agent=agent,
                        prompt=message,
                        requested_model=requested_model,
                        task_type=task_type,
                    )
                    for agent in base_targets
                ],
                rationale=f"Task type `{task_type}` matched, but decomposition is disabled.",
            )

        subtasks = decomposition.get("subtasks", [])
        if not isinstance(subtasks, list):
            subtasks = []

        if user_forced_agents:
            allowed_agents = set(base_targets)
        else:
            allowed_agents = set(enabled_agents if expand_from_router else base_targets)

        routes: list[TaskRoute] = []
        for item in subtasks[:max_subtasks]:
            if not isinstance(item, dict):
                continue
            agent = str(item.get("agent", "")).strip()
            if not agent or agent not in enabled_agents or agent not in allowed_agents:
                continue
            subtask_id = str(item.get("id", "")).strip() or None
            skill = str(item.get("skill", "")).strip() or None
            instruction = str(item.get("instruction", "")).strip() or None
            route_model = requested_model or self._skill_model(skill)
            route_prompt = self._subtask_prompt(
                message=message,
                task_type=task_type,
                subtask_id=subtask_id,
                instruction=instruction,
            )
            routes.append(
                TaskRoute(
                    agent=agent,
                    prompt=route_prompt,
                    requested_model=route_model,
                    task_type=task_type,
                    subtask_id=subtask_id,
                    skill=skill,
                    instruction=instruction,
                )
            )

        if not routes:
            return DispatchPlan(
                task_type=task_type,
                decomposed=False,
                strategy="parallel" if len(base_targets) > 1 else "direct",
                routes=[
                    TaskRoute(
                        agent=agent,
                        prompt=message,
                        requested_model=requested_model,
                        task_type=task_type,
                    )
                    for agent in base_targets
                ],
                rationale=f"Task type `{task_type}` matched but no eligible subtasks were available.",
            )

        return DispatchPlan(
            task_type=task_type,
            decomposed=True,
            strategy="parallel" if len(routes) > 1 else "direct",
            routes=routes,
            rationale=f"Decomposed `{task_type}` task into {len(routes)} routed subtasks.",
        )

    def _detect_task_type(self, message: str) -> str | None:
        lowered = message.lower()
        task_types = self._config.get("task_types", {})
        best_name: str | None = None
        best_score = 0
        for name, cfg in task_types.items():
            if not isinstance(cfg, dict):
                continue
            keywords = cfg.get("keywords", [])
            if not isinstance(keywords, list):
                continue
            score = sum(lowered.count(str(keyword).lower()) for keyword in keywords)
            if score > best_score:
                best_name = str(name)
                best_score = score
        return best_name if best_score > 0 else None

    def _skill_model(self, skill: str | None) -> str | None:
        if not skill:
            return None
        if skill not in self._model_router.list_skills():
            return None
        return self._model_router.get_skill_model(skill)

    @staticmethod
    def _subtask_prompt(
        *,
        message: str,
        task_type: str,
        subtask_id: str | None,
        instruction: str | None,
    ) -> str:
        header = f"[TaskType: {task_type}]"
        if subtask_id:
            header += f" [Subtask: {subtask_id}]"
        body = instruction or "Execute this subtask with high confidence."
        return f"{header}\nInstruction: {body}\n\nOriginal request:\n{message}"

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        return ordered
