from dataclasses import dataclass

from app.response.contracts import ResponseProfileName


@dataclass(frozen=True)
class ResponseProfile:
    name: ResponseProfileName
    max_chars: int
    show_sql: bool
    show_data_source: bool
    show_metric_definition: bool
    show_citations: bool
    show_confidence: bool
    generate_actions: bool
    tone: str
    forbidden_expressions: tuple[str, ...]


COMMON_FORBIDDEN = (
    "生产环境已上线",
    "真实客户",
    "真实经营收益",
    "必然导致",
    "确认因果",
)

PROFILES: dict[ResponseProfileName, ResponseProfile] = {
    ResponseProfileName.EXECUTIVE_BRIEF: ResponseProfile(
        name=ResponseProfileName.EXECUTIVE_BRIEF,
        max_chars=1800,
        show_sql=False,
        show_data_source=True,
        show_metric_definition=False,
        show_citations=True,
        show_confidence=True,
        generate_actions=True,
        tone="结论优先、审慎、面向经营决策",
        forbidden_expressions=COMMON_FORBIDDEN,
    ),
    ResponseProfileName.ANALYST_DETAILED: ResponseProfile(
        name=ResponseProfileName.ANALYST_DETAILED,
        max_chars=5000,
        show_sql=True,
        show_data_source=True,
        show_metric_definition=True,
        show_citations=True,
        show_confidence=True,
        generate_actions=False,
        tone="精确、可复核、区分事实与推断",
        forbidden_expressions=COMMON_FORBIDDEN,
    ),
    ResponseProfileName.OPERATION_ACTION: ResponseProfile(
        name=ResponseProfileName.OPERATION_ACTION,
        max_chars=2400,
        show_sql=False,
        show_data_source=True,
        show_metric_definition=False,
        show_citations=True,
        show_confidence=True,
        generate_actions=True,
        tone="可执行、分级、避免无证据因果结论",
        forbidden_expressions=COMMON_FORBIDDEN,
    ),
    ResponseProfileName.CONCISE_QUERY: ResponseProfile(
        name=ResponseProfileName.CONCISE_QUERY,
        max_chars=900,
        show_sql=False,
        show_data_source=False,
        show_metric_definition=False,
        show_citations=True,
        show_confidence=False,
        generate_actions=False,
        tone="简洁、直接、保留必要限定",
        forbidden_expressions=COMMON_FORBIDDEN,
    ),
}
