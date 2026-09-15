"""Runtime prompt injection API."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, Field

from ai_coworker.config import Settings, get_settings
from ai_coworker.prompts import PromptError, get_store

router = APIRouter(prefix="/prompts", tags=["prompts"])


class PromptBody(BaseModel):
    text: str = Field(min_length=1, description="Full prompt template (Markdown)")


class PromptCreateBody(BaseModel):
    id: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9._-]*$")
    text: str = Field(min_length=1)
    role: str = "system"
    description: str = ""
    variables: list[str] = Field(default_factory=list)


class PromptResponse(BaseModel):
    id: str
    text: str
    source: Literal["catalog"]
    role: str
    description: str
    variables: list[str]
    updated_at: str | None = None


class PromptListResponse(BaseModel):
    catalog_version: int
    prompts: list[PromptResponse]


def _require_admin(
    settings: Settings = Depends(get_settings),  # noqa: B008
    authorization: str | None = Header(default=None),
    x_prompts_token: str | None = Header(default=None, alias="X-Prompts-Token"),
) -> None:
    token = settings.prompts_admin_token
    if not token:
        return
    supplied = x_prompts_token
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if supplied != token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing prompts admin token")


def _to_response(record) -> PromptResponse:
    return PromptResponse(
        id=record.id,
        text=record.text,
        source=record.source,
        role=record.role,
        description=record.description,
        variables=record.variables,
        updated_at=record.updated_at,
    )


@router.get("", response_model=PromptListResponse)
async def list_prompts() -> PromptListResponse:
    store = get_store()
    return PromptListResponse(
        catalog_version=store.catalog_version(),
        prompts=[_to_response(r) for r in store.list_records()],
    )


@router.post("", response_model=PromptResponse, dependencies=[Depends(_require_admin)])
async def create_prompt(body: PromptCreateBody) -> PromptResponse:
    store = get_store()
    if body.id in store.list_ids():
        raise HTTPException(status.HTTP_409_CONFLICT, f"Prompt already exists: {body.id}")
    return _to_response(
        store.upsert_prompt(
            body.id,
            body.text,
            role=body.role,
            description=body.description,
            variables=body.variables,
        )
    )


@router.post("/reload", dependencies=[Depends(_require_admin)])
async def reload_defaults() -> dict[str, str]:
    """Reset catalog to bundled manifest defaults."""
    get_store().reload_files()
    return {"status": "ok", "message": "Catalog reset to manifest defaults"}


@router.get("/{prompt_id:path}", response_model=PromptResponse)
async def get_prompt(prompt_id: str) -> PromptResponse:
    try:
        return _to_response(get_store().get_record(prompt_id))
    except PromptError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.put(
    "/{prompt_id:path}",
    response_model=PromptResponse,
    dependencies=[Depends(_require_admin)],
)
async def put_prompt(prompt_id: str, body: PromptBody) -> PromptResponse:
    """Create or update a prompt in the catalog."""
    try:
        store = get_store()
        if prompt_id in store.list_ids():
            return _to_response(store.set_override(prompt_id, body.text))
        return _to_response(store.upsert_prompt(prompt_id, body.text))
    except PromptError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.delete(
    "/{prompt_id:path}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(_require_admin)],
)
async def delete_prompt(prompt_id: str) -> Response:
    """Permanently remove a prompt from the catalog."""
    try:
        get_store().delete_prompt(prompt_id)
    except PromptError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{prompt_id:path}/reset",
    response_model=PromptResponse,
    dependencies=[Depends(_require_admin)],
)
async def reset_prompt(prompt_id: str) -> PromptResponse:
    """Reset a prompt to the bundled manifest default."""
    try:
        return _to_response(get_store().clear_override(prompt_id))
    except PromptError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
