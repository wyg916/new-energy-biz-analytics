__all__ = ["SQLBotEngine"]


def __getattr__(name: str):
    if name == "SQLBotEngine":
        from app.query_engines.sqlbot.engine import SQLBotEngine

        return SQLBotEngine
    raise AttributeError(name)
