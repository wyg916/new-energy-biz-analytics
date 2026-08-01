from app.platform.query_engine import QueryContext, QueryRequest
from app.query_engines.sqlbot.contracts import SQLBotSession
from app.query_engines.sqlbot.error_mapper import (
    SQLBotEngineError,
    SQLBotErrorCode,
)


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
        "question": request.question,
        "chat_id": int(session.external_chat_id),
        "token": session.access_token,
        "stream": False,
        "lang": request.locale,
        "datasource_id": context.datasource_id,
        "return_img": False,
    }
