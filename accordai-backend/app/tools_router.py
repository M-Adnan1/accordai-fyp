"""Admin endpoints for managing a client's callable tools.

/generate-schema turns a plain-English description into a reviewed JSON Schema
(it saves nothing); /create persists the (possibly owner-edited) result.
"""
import json
import re
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from groq import Groq
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.config import get_settings
from app.deps import get_current_user, require_admin
from app.models import User
from app.security import encrypt_credential
from app.tool_executor import validate_endpoint_url, UnsafeURLError
import app.crud as crud

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()
groq_client = Groq(api_key=settings.GROQ_API_KEY)

TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
ALLOWED_AUTH_TYPES = {"bearer", "api_key_header", "none"}
ALLOWED_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

SCHEMA_GEN_SYSTEM_PROMPT = (
    "You convert plain-English descriptions of a business action into an OpenAI-style "
    "function definition. Respond with ONLY a valid JSON object, no prose, matching exactly:\n"
    '{"name": "snake_case_name", "description": "when the assistant should call this", '
    '"parameters": {"type": "object", "properties": {...}, "required": [...]}}\n'
    "Rules: name is lowercase snake_case; description says WHEN to call the function "
    "during a customer phone call; every property has a type and a description; "
    "list genuinely mandatory fields in required."
)


class SchemaGenRequest(BaseModel):
    description: str = Field(min_length=10)


class ToolCreateRequest(BaseModel):
    name: str
    description: str = Field(min_length=1)
    parameters: dict
    endpoint_url: str
    http_method: str = "POST"
    auth_type: str = "none"
    auth_credential: Optional[str] = None
    auth_header_name: Optional[str] = None
    requires_confirmation: bool = True


class ToolUpdateRequest(BaseModel):
    """Partial update — only fields explicitly sent are changed.

    Send a new auth_credential to rotate the secret; it is left untouched
    otherwise. Set is_active=false to disable a tool without deleting it.
    """
    name: Optional[str] = None
    description: Optional[str] = None
    parameters: Optional[dict] = None
    endpoint_url: Optional[str] = None
    http_method: Optional[str] = None
    auth_type: Optional[str] = None
    auth_credential: Optional[str] = None
    auth_header_name: Optional[str] = None
    requires_confirmation: Optional[bool] = None
    is_active: Optional[bool] = None


def _validate_tool_schema(name: str, description: str, parameters: dict) -> Optional[str]:
    """Returns an error message, or None if the schema is acceptable."""
    if not TOOL_NAME_PATTERN.match(name or ""):
        return f"name must be lowercase snake_case (got '{name}')"
    if not (description or "").strip():
        return "description must be non-empty"
    if not isinstance(parameters, dict) or parameters.get("type") != "object":
        return 'parameters must be an object schema with "type": "object"'
    if not isinstance(parameters.get("properties"), dict):
        return 'parameters must contain a "properties" object'
    try:
        Draft202012Validator.check_schema(parameters)
    except SchemaError as e:
        return f"parameters is not a valid JSON Schema: {e.message}"
    return None


def _harden_parameters(parameters: dict) -> dict:
    """Force additionalProperties:false at the top level of a tool's schema.

    Done deterministically in code (not left to the schema-generating model) so
    every stored tool rejects arguments the model invents beyond the declared
    properties. Returns the same dict for convenient chaining.

    Note: this only locks the top-level object — the level tool arguments live
    at. Nested object properties keep whatever the schema declares.
    """
    if isinstance(parameters, dict) and parameters.get("type") == "object":
        parameters["additionalProperties"] = False
    return parameters


def _serialize_tool(tool) -> dict:
    """API shape for a ClientTool — auth_credential is deliberately excluded."""
    return {
        "id": tool.id,
        "client_id": tool.client_id,
        "name": tool.name,
        "description": tool.description,
        "parameters_schema": tool.parameters_schema,
        "endpoint_url": tool.endpoint_url,
        "http_method": tool.http_method,
        "auth_type": tool.auth_type,
        "auth_header_name": tool.auth_header_name,
        "requires_confirmation": tool.requires_confirmation,
        "is_active": tool.is_active,
        "created_at": tool.created_at,
    }


def _generate_schema_once(description: str, extra_instruction: str = "") -> dict:
    completion = groq_client.chat.completions.create(
        model=settings.GROQ_MODEL,
        messages=[
            {"role": "system", "content": SCHEMA_GEN_SYSTEM_PROMPT + extra_instruction},
            {"role": "user", "content": description},
        ],
        temperature=0.1,
        max_tokens=1024,
        response_format={"type": "json_object"},
    )
    return json.loads(completion.choices[0].message.content)


# Authenticated (admin) because each call spends LLM tokens; persists nothing.
@router.post("/generate-schema")
async def generate_schema(body: SchemaGenRequest, user: User = Depends(require_admin)):
    """Turn a plain-English tool description into a JSON Schema for review.

    Saves nothing — the owner reviews/edits the result, then calls /create.
    """
    error = None
    for attempt in range(2):
        extra = ""
        if attempt == 1:
            extra = (
                f"\n\nYour previous output was rejected: {error}. "
                "Output ONLY the corrected JSON object, strictly matching the required shape."
            )
        try:
            generated = _generate_schema_once(body.description, extra)
        except Exception as e:  # invalid JSON from the model, or a Groq API error
            error = f"model did not return valid JSON ({type(e).__name__})"
            logger.warning(f"Schema generation attempt {attempt + 1} failed: {e}")
            continue

        error = _validate_tool_schema(
            generated.get("name", ""),
            generated.get("description", ""),
            generated.get("parameters", {}),
        )
        if error is None:
            return {
                "name": generated["name"],
                "description": generated["description"],
                "parameters": _harden_parameters(generated["parameters"]),
            }
        logger.warning(f"Schema generation attempt {attempt + 1} invalid: {error}")

    raise HTTPException(
        status_code=422,
        detail=f"Could not generate a valid tool schema: {error}. "
               "Try rephrasing the description with the action, its inputs, and which are required."
    )


@router.post("/create")
async def create_tool(
    body: ToolCreateRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """Persist a reviewed tool definition for the authenticated tenant."""
    client_id = user.client_id
    error = _validate_tool_schema(body.name, body.description, body.parameters)
    if error:
        raise HTTPException(status_code=422, detail=error)

    # Lock the schema so the model can't add undeclared arguments at call time.
    # Enforced here (not just in /generate-schema) to cover owner-edited schemas.
    _harden_parameters(body.parameters)

    method = body.http_method.upper()
    if method not in ALLOWED_HTTP_METHODS:
        raise HTTPException(status_code=422, detail=f"http_method must be one of {sorted(ALLOWED_HTTP_METHODS)}")
    if body.auth_type not in ALLOWED_AUTH_TYPES:
        raise HTTPException(status_code=422, detail=f"auth_type must be one of {sorted(ALLOWED_AUTH_TYPES)}")
    if body.auth_type != "none" and not body.auth_credential:
        raise HTTPException(status_code=422, detail=f"auth_credential is required for auth_type '{body.auth_type}'")

    try:
        validate_endpoint_url(body.endpoint_url)
    except UnsafeURLError as e:
        raise HTTPException(status_code=422, detail=str(e))

    encrypted = encrypt_credential(body.auth_credential) if body.auth_credential else None
    header_name = body.auth_header_name
    if body.auth_type == "api_key_header" and not header_name:
        header_name = "X-API-Key"

    try:
        tool = await crud.create_client_tool(
            db,
            client_id=client_id,
            name=body.name,
            description=body.description,
            parameters_schema=body.parameters,
            endpoint_url=body.endpoint_url,
            http_method=method,
            auth_type=body.auth_type,
            auth_credential=encrypted,
            auth_header_name=header_name,
            requires_confirmation=body.requires_confirmation,
        )
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"A tool named '{body.name}' already exists for this client."
        )

    logger.info(f"Created tool '{tool.name}' (id={tool.id}) for client {client_id}")
    return _serialize_tool(tool)


@router.patch("/update")
async def update_tool(
    tool_id: int,
    body: ToolUpdateRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    client_id = user.client_id
    """Apply a partial update to an existing tool owned by this client.

    Only the fields present in the request body are changed. The auth
    credential is re-encrypted only when a new one is supplied.
    """
    provided = body.model_dump(exclude_unset=True)
    if not provided:
        raise HTTPException(status_code=422, detail="No fields to update.")

    tool = await crud.get_tool_by_id(db, tool_id)
    if tool is None or tool.client_id != client_id:
        raise HTTPException(status_code=404, detail="Tool not found for this client.")

    updates: dict = {}

    # Name / description / parameters: validate the resulting schema as a whole.
    if any(k in provided for k in ("name", "description", "parameters")):
        eff_name = provided.get("name", tool.name)
        eff_description = provided.get("description", tool.description)
        eff_parameters = provided.get("parameters", tool.parameters_schema)
        error = _validate_tool_schema(eff_name, eff_description, eff_parameters)
        if error:
            raise HTTPException(status_code=422, detail=error)
        if "name" in provided:
            updates["name"] = eff_name
        if "description" in provided:
            updates["description"] = eff_description
        if "parameters" in provided:
            updates["parameters_schema"] = _harden_parameters(eff_parameters)

    if "http_method" in provided:
        method = (provided["http_method"] or "").upper()
        if method not in ALLOWED_HTTP_METHODS:
            raise HTTPException(status_code=422, detail=f"http_method must be one of {sorted(ALLOWED_HTTP_METHODS)}")
        updates["http_method"] = method

    if "endpoint_url" in provided:
        try:
            validate_endpoint_url(provided["endpoint_url"])
        except UnsafeURLError as e:
            raise HTTPException(status_code=422, detail=str(e))
        updates["endpoint_url"] = provided["endpoint_url"]

    if "requires_confirmation" in provided:
        updates["requires_confirmation"] = provided["requires_confirmation"]
    if "is_active" in provided:
        updates["is_active"] = provided["is_active"]

    # Auth: validate against the effective auth_type after the update.
    eff_auth_type = provided.get("auth_type", tool.auth_type)
    if "auth_type" in provided:
        if eff_auth_type not in ALLOWED_AUTH_TYPES:
            raise HTTPException(status_code=422, detail=f"auth_type must be one of {sorted(ALLOWED_AUTH_TYPES)}")
        updates["auth_type"] = eff_auth_type

    if eff_auth_type == "none":
        # Switching to "none" clears any stored credential/header.
        if "auth_type" in provided:
            updates["auth_credential"] = None
            updates["auth_header_name"] = None
    else:
        if "auth_credential" in provided:
            if not provided["auth_credential"]:
                raise HTTPException(status_code=422, detail=f"auth_credential cannot be empty for auth_type '{eff_auth_type}'")
            updates["auth_credential"] = encrypt_credential(provided["auth_credential"])
        elif "auth_type" in provided and not tool.auth_credential:
            raise HTTPException(status_code=422, detail=f"auth_credential is required for auth_type '{eff_auth_type}'")

        if "auth_header_name" in provided:
            updates["auth_header_name"] = provided["auth_header_name"]
        eff_header = updates.get("auth_header_name", tool.auth_header_name)
        if eff_auth_type == "api_key_header" and not eff_header:
            updates["auth_header_name"] = "X-API-Key"

    if not updates:
        return _serialize_tool(tool)

    try:
        tool = await crud.update_client_tool(db, tool, updates)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"A tool named '{updates.get('name', tool.name)}' already exists for this client."
        )

    logger.info(f"Updated tool '{tool.name}' (id={tool.id}) for client {client_id}: fields={sorted(updates)}")
    return _serialize_tool(tool)


@router.delete("/delete/{tool_id}")
async def delete_tool(
    tool_id: int,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    client_id = user.client_id
    """Deactivate a tool owned by this client.

    This is a soft delete (sets is_active=false): tool_call_logs reference the
    tool by id, so the row is kept to preserve the audit trail. A deactivated
    tool stops appearing in /list and is no longer offered to the agent, and can
    be re-enabled via /update with is_active=true.
    """
    tool = await crud.get_tool_by_id(db, tool_id)
    if tool is None or tool.client_id != client_id:
        raise HTTPException(status_code=404, detail="Tool not found for this client.")

    if not tool.is_active:
        return {"message": f"Tool '{tool.name}' was already inactive.", "id": tool.id}

    await crud.update_client_tool(db, tool, {"is_active": False})
    logger.info(f"Deactivated tool '{tool.name}' (id={tool.id}) for client {client_id}")
    return {"message": f"Tool '{tool.name}' deactivated.", "id": tool.id}


@router.get("/list")
async def list_tools(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Active tools for the authenticated tenant (credentials excluded)."""
    tools = await crud.get_active_tools(db, user.client_id)
    return [_serialize_tool(t) for t in tools]
