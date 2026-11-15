"""Application contracts. Future backends implement these without changing the agent loop."""
from dataclasses import dataclass
from typing import Protocol, Literal


@dataclass(frozen=True)
class Principal:
    user_id: str
    scopes: frozenset[str]


class Authorizer(Protocol):
    def require(self, principal: Principal, user_id: str, scope: str) -> None: ...


class OwnerOnly:
    def require(self, principal: Principal, user_id: str, scope: str) -> None:
        if principal.user_id != user_id or scope not in principal.scopes:
            raise PermissionError("Access denied")


class EnterpriseData(Protocol):
    def search(self, principal: Principal, query: str, tag: str) -> list[dict]: ...
    def environment(self, principal: Principal, project: str) -> dict: ...


class Specialist(Protocol):
    role: Literal["research", "analysis", "verification"]

    def execute(self, task: str, context: dict) -> dict: ...


class PreferenceAlignment(Protocol):
    def propose(self, actor: Principal) -> dict: ...
