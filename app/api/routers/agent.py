from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlmodel import Session

from app.ai.audio_convert import AudioConversionError
from app.api.deps import get_container, merchant_or_404, tool_context
from app.api.schemas.agent import ChatIn, ChatOut, EventOut, ToolCallOut, VoiceOut
from app.container import Container
from app.db import get_session
from app.services import message_service
from app.services.errors import Invalid

router = APIRouter(tags=["agent"])
MAX_AUDIO_BYTES = 5 * 1024 * 1024


def _traces(traces) -> list[ToolCallOut]:
    return [ToolCallOut(name=t.name, arguments=t.arguments, result=t.result) for t in traces]


def _log_turn(session: Session, merchant_id: int, channel: str, user_text: str, reply_text: str, traces, audio_url=None,
              trace: dict | None = None) -> None:
    message_service.log_message(session, merchant_id, channel, "in", user_text)
    message_service.log_message(session, merchant_id, channel, "out", reply_text, audio_url,
                                [{"name": t.name, "arguments": t.arguments, "result": t.result} for t in traces], trace)


@router.post("/agent/chat", response_model=ChatOut)
def chat(body: ChatIn, session: Session = Depends(get_session), container: Container = Depends(get_container)):
    merchant = merchant_or_404(session, body.merchant_id)
    ctx = tool_context(session, merchant, container)
    reply = container.agent.respond(ctx, body.text, body.channel, body.language or merchant.language, body.history)
    _log_turn(session, merchant.id, body.channel, body.text, reply.text, reply.traces, trace=reply.trace.to_dict())
    session.commit()
    return ChatOut(text=reply.text, tool_calls=_traces(reply.traces), source=reply.source, trace=reply.trace.to_dict())


@router.post("/agent/voice", response_model=VoiceOut)
def voice(merchant_id: int = Form(...), file: UploadFile = File(...), session: Session = Depends(get_session),
          container: Container = Depends(get_container)):
    merchant = merchant_or_404(session, merchant_id)
    audio = file.file.read(MAX_AUDIO_BYTES + 1)
    if len(audio) > MAX_AUDIO_BYTES:
        raise Invalid("Audio is larger than 5 MB")
    try:
        r = container.voice.handle(tool_context(session, merchant, container), audio, file.filename or "audio.wav")
    except AudioConversionError as e:
        raise Invalid(str(e)) from e
    _log_turn(session, merchant.id, "soundbox", r.transcript, r.text, r.traces, r.audio_url, r.trace)
    session.commit()
    return VoiceOut(transcript=r.transcript, language_code=r.language_code, text=r.text, audio_url=r.audio_url,
                    tool_calls=_traces(r.traces), source=r.source)


@router.get("/merchants/{merchant_id}/events", response_model=list[EventOut])
def events(merchant_id: int, after_id: int = 0, session: Session = Depends(get_session)):
    """Soundbox-style announcements (payment received, due tomorrow). The app polls this."""
    merchant_or_404(session, merchant_id)
    return [EventOut(id=m.id, text=m.text) for m in message_service.list_events(session, merchant_id, after_id)]
