"""Where LangGraph keeps thread state (conversation memory and pending confirmations)."""
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver


def memory_checkpointer() -> BaseCheckpointSaver:
    return InMemorySaver()


def postgres_checkpointer(database_url: str) -> BaseCheckpointSaver:
    """Durable checkpoints in Postgres, so memory and pending confirmations survive restarts."""
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(database_url.replace("postgresql+psycopg://", "postgresql://"), max_size=5, open=True,
                          kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})
    saver = PostgresSaver(pool)
    saver.setup()
    return saver
