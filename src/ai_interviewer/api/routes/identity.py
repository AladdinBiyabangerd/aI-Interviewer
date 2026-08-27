"""Authenticated identity self-service contracts."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from ai_interviewer.identity.authorization import require_scopes
from ai_interviewer.identity.service import Principal

router = APIRouter(prefix="/identity", tags=["identity"])


class CurrentAccountResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: UUID


@router.get("/me", response_model=CurrentAccountResponse, summary="Current account")
async def current_account(
    principal: Annotated[Principal, Depends(require_scopes("profile:read"))],
) -> CurrentAccountResponse:
    return CurrentAccountResponse(account_id=principal.account_id)
