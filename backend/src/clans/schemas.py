from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    is_test_user: bool


class InitialPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    currency: Literal["KES", "BTC"] = "KES"
    member_vote_quorum: int = Field(default=1, ge=1, le=1000)
    signer_threshold: int = Field(default=2, ge=1, le=100)
    beneficiary_can_approve: bool = False


class CreateClan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1, max_length=100)
    policy: InitialPolicy = Field(default_factory=InitialPolicy)

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Clan name must contain visible text")
        return value.strip()


class PolicyView(InitialPolicy):
    model_config = ConfigDict(from_attributes=True)

    id: str
    version: int


class ClanView(BaseModel):
    id: str
    name: str
    status: str
    created_at: str
    policy: PolicyView
    member_count: int
    signer_count: int
    governance_ready: bool
    payment_mode: Literal["simulation"] = "simulation"


class MemberView(BaseModel):
    user: UserView
    role: str
    is_signer: bool


class HealthView(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    payment_mode: Literal["simulation"] = "simulation"
    demo_auth_enabled: bool
    payment_execution_enabled: Literal[False] = False


class ProviderHealth(BaseModel):
    reachable: bool
    synchronized: bool
    execution_enabled: Literal[False] = False
