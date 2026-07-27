from fastapi import APIRouter, Form, Request, Depends
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Gather
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.llm_service import get_ai_response
from app.models import CallStatus
import app.crud as crud
import logging
import time
logger = logging.getLogger(__name__)
router = APIRouter()

# Keywords that signal the user wants to end the call
GOODBYE_PHRASES = [
    "bye", "goodbye", "good bye", "see you", "see ya",
    "that's all", "thats all", "no more", "nothing else",
    "i'm done", "im done", "i am done", "all done",
    "thank you bye", "thanks bye", "no thank you",
    "no thanks", "hang up", "end call", "quit"
]

def is_goodbye(text: str) -> bool:
    """Check if user's message contains a goodbye intent."""
    text_lower = text.lower().strip()
    return any(phrase in text_lower for phrase in GOODBYE_PHRASES)
@router.post("/incoming")
async def handle_incoming_call(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    form = await request.form()
    call_sid = form.get("CallSid")
    from_number = form.get("From")
    to_number = form.get("To")

    logger.info(f"Incoming call from {from_number} to {to_number} (SID: {call_sid})")

    tenant = await crud.get_client_by_number(db, to_number)
    if not tenant:
        logger.warning(f"No active client found for Twilio number {to_number}. Rejecting call.")
        response = VoiceResponse()
        response.say(
            "We're sorry, this number is not currently in service. Goodbye.",
            voice="Polly.Joanna"
        )
        response.hangup()
        return Response(content=str(response), media_type="application/xml")

    await crud.create_call(db, call_sid, from_number, to_number, client_id=tenant.id)

    response = VoiceResponse()
    response.say(tenant.greeting, voice=tenant.voice)

    gather = Gather(
        input="speech",
        action="/voice/process",
        method="POST",
        speech_timeout="auto",
        speech_model="phone_call",
        language="en-US"
    )
    response.append(gather)

    response.say("I didn't hear anything. Please call back when you're ready.", voice=tenant.voice)
    response.hangup()

    return Response(content=str(response), media_type="application/xml")


@router.post("/process")
async def process_speech(
    request: Request,
    SpeechResult: str = Form(None),
    CallSid: str = Form(None),
    db: AsyncSession = Depends(get_db)
):
    logger.info(f"User said: {SpeechResult}")

    response = VoiceResponse()

    call = await crud.get_call_by_sid(db, CallSid)
    voice = call.client.voice if call and call.client else "Polly.Joanna"

    # No call record means we can't resolve the tenant — end gracefully
    # instead of crashing on call.client_id below.
    if not call:
        logger.warning(f"No call record found for SID {CallSid}. Ending call.")
        response.say("We're sorry, something went wrong. Please call again. Goodbye.", voice=voice)
        response.hangup()
        return Response(content=str(response), media_type="application/xml")

    if not SpeechResult:
        response.say("Sorry, I didn't catch that. Could you repeat?", voice=voice)
        response.redirect("/voice/incoming")
        return Response(content=str(response), media_type="application/xml")

    await crud.update_call_status(db, CallSid, CallStatus.IN_PROGRESS)
    await crud.add_message(db, CallSid, "user", SpeechResult)

    # A tool call awaiting confirmation must be resolved by the LLM flow —
    # phrases like "no thanks" are a decline of the action, not a goodbye.
    pending_tool = await crud.get_pending_tool_call(db, call.id)

    # Check for goodbye intent BEFORE calling the LLM
    if not pending_tool and is_goodbye(SpeechResult):
        logger.info(f"Goodbye intent detected: '{SpeechResult}'")
        response.say(
            "It was a pleasure helping you today. Before you go, please rate your experience.",
            voice=voice
        )
        # Redirect to rating flow
        response.redirect("/voice/rate")
        return Response(content=str(response), media_type="application/xml")

    # Normal flow — call LLM
    history = await crud.get_conversation_history(db, CallSid)

    start = time.time()
    ai_response = await get_ai_response(
        SpeechResult, client_id=call.client_id, db=db,
        conversation_history=history, call_id=call.id
    )
    response_time_ms = int((time.time() - start) * 1000)

    logger.info(f"🤖 AI response: {ai_response}")
    logger.info(f"⏱️ Response time: {response_time_ms}ms")

    await crud.add_message(db, CallSid, "assistant", ai_response, response_time_ms)

    # Check if the AI itself is wrapping up the conversation
    if is_goodbye(ai_response):
        response.say(ai_response, voice=voice)
        response.redirect("/voice/rate")
        return Response(content=str(response), media_type="application/xml")

    # Continue conversation
    response.say(ai_response, voice=voice)

    gather = Gather(
        input="speech",
        action="/voice/process",
        method="POST",
        # Numeric timeout (not "auto"): callers pause between digit groups when
        # speaking phone numbers; auto endpointing truncated at the first pause.
        # Costs up to 3s of silence at the end of each in-conversation turn.
        speech_timeout="2",
        speech_model="googlev2_telephony",
        language="en-US"
    )
    # gather.say("Is there anything else I can help you with?", voice=voice)
    response.append(gather)
    response.say("Thank you for calling. Goodbye!", voice=voice)
    response.redirect("/voice/rate")

    return Response(content=str(response), media_type="application/xml")


@router.post("/rate")
async def rate_call(
    request: Request,
    CallSid: str = Form(None),
    db: AsyncSession = Depends(get_db)
):
    """Ask the user to rate their experience before hanging up."""
    response = VoiceResponse()

    call = await crud.get_call_by_sid(db, CallSid)
    voice = call.client.voice if call and call.client else "Polly.Joanna"

    gather = Gather(
        input="dtmf",           # keypad input, not speech
        action="/voice/save-rating",
        method="POST",
        num_digits=1,           # only 1 digit
        timeout=10              # wait 10 seconds for input
    )
    gather.say(
        "Please press 1 if you were satisfied with our service, or press 0 if you were not.",
        voice=voice
    )
    response.append(gather)

    # If no input, skip rating and hang up
    response.say("We didn't receive your rating. Thank you for calling. Goodbye!", voice=voice)
    response.hangup()

    return Response(content=str(response), media_type="application/xml")


@router.post("/save-rating")
async def save_rating(
    request: Request,
    CallSid: str = Form(None),
    Digits: str = Form(None),      # Twilio sends keypad input as "Digits"
    db: AsyncSession = Depends(get_db)
):
    """Save the satisfaction rating and end the call."""
    logger.info(f"Rating received for {CallSid}: {Digits}")

    response = VoiceResponse()

    call = await crud.get_call_by_sid(db, CallSid)
    voice = call.client.voice if call and call.client else "Polly.Joanna"

    if Digits in ("0", "1"):
        rating = int(Digits)
        await crud.update_call_rating(db, CallSid, rating)

        if rating == 1:
            response.say(
                "Thank you for your positive feedback! Have a great day. Goodbye!",
                voice=voice
            )
        else:
            response.say(
                "We're sorry to hear that. We'll work on improving. Thank you for calling. Goodbye!",
                voice=voice
            )
    else:
        # Invalid key pressed
        response.say(
            "Invalid input. Thank you for calling. Goodbye!",
            voice=voice
        )

    response.hangup()
    return Response(content=str(response), media_type="application/xml")


@router.post("/status")
async def call_status(
    request: Request,
    CallSid: str = Form(None),
    call_status_str: str = Form(None, alias="CallStatus"),
    CallDuration: int = Form(None),
    db: AsyncSession = Depends(get_db)
):
    logger.info(f"Call {CallSid} status: {call_status_str}")
    if call_status_str == "completed":
        await crud.update_call_status(db, CallSid, CallStatus.COMPLETED, CallDuration)
    elif call_status_str in ["busy", "failed", "no-answer"]:
        await crud.update_call_status(db, CallSid, CallStatus.FAILED)
    return Response(status_code=200)