from app.platform.query_engine import QueryContext, QueryRequest
from app.query_engines.sqlbot.contracts import SQLBotSession
from app.query_engines.sqlbot.error_mapper import (
    SQLBotEngineError,
    SQLBotErrorCode,
)
from app.query_engines.sqlbot.prompt_context import build_governed_question


def map_question_request(
    request: QueryRequest,
    context: QueryContext,
    session: SQLBotSession,
) -> dict:
    if not context.datasource_id:
        raise SQLBotEngineError(
            SQLBotErrorCode.POLICY_DENIED,
            "SQLBot datasource 未绑定当前 ACTIVE 版本",
        )
    return {
        "question": build_governed_question(
            request.question,
            scenario_id=request.scenario_id,
            prompt_context=context.prompt_context,
        ),
        "chat_id": int(session.external_chat_id),
        "token": session.access_token,
        "stream": False,
        "lang": request.locale,
        "datasource_id": context.datasource_id,
        "return_img": False,
    }
