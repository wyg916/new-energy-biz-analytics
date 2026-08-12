"""SQLBot v1.10.0 local-acceptance extension for generate-only NL2SQL.

The upstream MCP question route runs generated SQL before returning it. This
wrapper exposes one additional authenticated-in-body MCP route that stops at
SQLBot's native GENERATE_SQL finish step. The platform remains responsible for
AST/schema/join/permission/cost guards and the only permitted execution.
"""

import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from starlette.responses import JSONResponse

# SQLBot v1.10 uses one OpenAI-compatible factory for all protocol=1 models.
# MiMo's official endpoint requires the credential in ``api-key`` rather than
# relying on the standard Authorization header. Install the narrow adapter
# before importing the assembled upstream application so status probes and
# real chat traffic share exactly the same transport contract.
from apps.ai_model.model_factory import BaseChatOpenAI, OpenAILLM


MIMO_API_DOMAIN = "https://api.xiaomimimo.com/v1"
_original_openai_init = OpenAILLM._init_llm


def _provider_aware_openai_init(self):
    if (self.config.api_base_url or "").rstrip("/") != MIMO_API_DOMAIN:
        return _original_openai_init(self)
    params = dict(self.config.additional_params)
    if "default_headers" in params:
        raise ValueError("persisted default_headers are not allowed")
    return BaseChatOpenAI(
        model=self.config.model_name,
        # The OpenAI client always constructs an Authorization header. MiMo
        # authenticates with the explicit api-key header below; use a harmless
        # fixed placeholder so the real credential is not duplicated there.
        api_key="mimo-runtime-api-key-header",
        base_url=self.config.api_base_url,
        default_headers={"api-key": self.config.api_key or ""},
        stream_usage=True,
        **params,
    )


OpenAILLM._init_llm = _provider_aware_openai_init

# Import the fully assembled upstream application first. Importing chat modules
# before main causes SQLBot datasource modules to re-enter each other.
from main import app, mcp_app
from apps.chat.api.chat import question_answer_inner
from apps.chat.models.chat_model import ChatFinishStep, ChatMcp, McpQuestion
from apps.mcp.mcp import get_user
from common.core.config import settings
from common.core.deps import SessionDep
from common.error import SingleMessageError


router = APIRouter(tags=["mcp"], prefix="/mcp")


def _datasource_id(value: Optional[int | str]) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid datasource ID") from exc
    if isinstance(value, str):
        return None
    raise HTTPException(status_code=400, detail="Invalid datasource ID")


@router.post("/mcp_generate_sql", operation_id="mcp_generate_sql")
async def mcp_generate_sql(session: SessionDep, chat: McpQuestion):
    """Generate SQL through the real SQLBot model without executing the SQL."""
    session_user = get_user(session, chat.token)
    if chat.lang in {"zh-CN", "zh-TW", "en", "ko-KR"}:
        session_user.language = chat.lang
    request = ChatMcp(
        token=chat.token,
        chat_id=chat.chat_id,
        question=chat.question,
        datasource_id=_datasource_id(chat.datasource_id),
    )
    try:
        response = await question_answer_inner(
            session=session,
            current_user=session_user,
            request_question=request,
            in_chat=False,
            stream=False,
            finish_step=ChatFinishStep.GENERATE_SQL,
            return_img=False,
        )
        # v1.10's non-stream path deliberately converts every structured
        # {"success": false} model refusal into HTTP 500. Recover only that
        # exact envelope. Other 500 responses remain failures.
        if isinstance(response, JSONResponse) and response.status_code == 500:
            payload = json.loads(response.body)
            if isinstance(payload, dict) and payload.get("success") is False:
                return {"success": False, "refusal": "PRE_SQL_MODEL_REFUSAL"}
        return response
    except SingleMessageError:
        # v1.10 raises this after the model has deliberately returned
        # {"success": false, ...}. Preserve the refusal as a successful HTTP
        # exchange so the platform can distinguish it from runtime failure.
        # The upstream prose is intentionally not forwarded or audited.
        return {"success": False, "refusal": "PRE_SQL_MODEL_REFUSAL"}


# XPack installs its SPA catch-all while ``main`` is imported.  FastAPI uses
# registration order, so a route appended after that catch-all is answered
# with 405 before it can reach this handler.  Register normally (to preserve
# dependency/OpenAPI behaviour), then move only this acceptance route ahead of
# the already-installed catch-all.
existing_route_ids = {id(route) for route in app.router.routes}
app.include_router(router, prefix=settings.API_V1_STR)
generate_only_routes = [
    route for route in app.router.routes if id(route) not in existing_route_ids
]
app.router.routes[:] = generate_only_routes + [
    route for route in app.router.routes if id(route) in existing_route_ids
]
