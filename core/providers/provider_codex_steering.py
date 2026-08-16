"""Codex same-turn input adapter mixin."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.providers.models import RuntimeSteerResult

if TYPE_CHECKING:
    from core.skills.models import SkillDefinition


class CodexSteeringMixin:
    def steer_turn(
        self,
        session_id: str,
        *,
        input_text: str,
        client_message_id: str | None = None,
        expected_provider_turn_id: str | None = None,
        invoked_skills: list["SkillDefinition"] | None = None,
    ) -> RuntimeSteerResult:
        """Admit additional text into the active Codex app-server turn."""
        from core.providers.codex_app_server import steer_codex_app_server_turn

        return steer_codex_app_server_turn(
            session_id,
            input_text=input_text,
            client_message_id=client_message_id,
            expected_provider_turn_id=expected_provider_turn_id,
            invoked_skills=invoked_skills,
        )
