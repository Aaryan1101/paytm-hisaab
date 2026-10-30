"""One confirm-before-act mechanism for bills, duplicates, cash entries and payments.

    ask (interrupt: waits for the user's choice) --> apply (runs the business action)

State is checkpointed, so a pending decision survives a restart, a second tap on the same button does nothing,
only the owner can answer, and stale requests expire. The business actions themselves are unchanged
(channels.whatsapp.button_actions): the graph adds durability and safety around them.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlmodel import Session

from app.ai.graph.pending import Option, PendingAction
from app.channels.base import Notifier
from app.channels.whatsapp import button_actions
from app.services.errors import ServiceError

MAX_AGE = timedelta(hours=24)
ALREADY_DONE = "Yeh pehle hi ho chuka hai."
EXPIRED = "Yeh request purani ho gayi hai. Kripya dobara bhejein."
NOT_FOUND = "Yeh request mujhe nahi mili."
NOT_YOURS = "Yeh request aapki nahi hai."
BAD_CHOICE = "Yeh option samajh nahi aaya."


class State(TypedDict, total=False):
    merchant_id: int
    kind: str
    ref_id: int
    choices: list[str]
    choice: str
    reply: str


class Confirmations:
    def __init__(self, checkpointer: BaseCheckpointSaver, max_age: timedelta = MAX_AGE):
        self._checkpointer, self._max_age = checkpointer, max_age

    def start(self, merchant_id: int, pending: PendingAction) -> str:
        """Open a pending decision and return its thread id (used inside button ids)."""
        thread = f"c-{uuid.uuid4().hex[:12]}"
        graph = self._graph(None, None)
        graph.invoke({"merchant_id": merchant_id, "kind": pending.kind, "ref_id": pending.ref_id,
                      "choices": [o.choice for o in pending.options]}, self._config(thread))
        return thread

    def resume(self, session: Session, notifier: Notifier, merchant_id: int, thread: str, choice: str) -> str:
        """Apply the user's choice. Returns the reply text; safe to call twice."""
        graph = self._graph(session, notifier)
        config = self._config(thread)
        snap = graph.get_state(config)
        if not snap.values:
            return NOT_FOUND
        if snap.values["merchant_id"] != merchant_id:
            return NOT_YOURS
        if not snap.next:
            return ALREADY_DONE
        if snap.created_at and datetime.now(timezone.utc) - datetime.fromisoformat(snap.created_at) > self._max_age:
            return EXPIRED
        if choice not in snap.values["choices"]:
            return BAD_CHOICE
        return graph.invoke(Command(resume=choice), config)["reply"]

    @staticmethod
    def _config(thread: str) -> dict:
        return {"configurable": {"thread_id": thread}, "tags": ["hisaab", "confirmation"]}

    def _graph(self, session: Session | None, notifier: Notifier | None):
        def ask(state: State) -> dict:
            return {"choice": interrupt({"kind": state["kind"], "ref_id": state["ref_id"], "choices": state["choices"]})}

        def apply(state: State) -> dict:
            try:
                reply = button_actions.perform(session, notifier, state["merchant_id"], state["kind"], state["ref_id"], state["choice"])
            except ServiceError as e:
                reply = f"Nahi ho paya: {e.message}"
            return {"reply": reply}

        g = StateGraph(State)
        g.add_node("ask", ask)
        g.add_node("apply", apply)
        g.add_edge(START, "ask")
        g.add_edge("ask", "apply")
        g.add_edge("apply", END)
        return g.compile(checkpointer=self._checkpointer)


def buttons_for(thread: str, options: tuple[Option, ...]):
    """Button ids for a pending decision: 'g:<thread>:<choice>' (graph-resumed, as opposed to the legacy stateless ids)."""
    from app.channels.base import Button
    return [Button(f"g:{thread}:{o.choice}", o.title) for o in options]
