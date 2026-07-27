import asyncio
import json
from groq import Groq, BadRequestError
from jsonschema import Draft202012Validator
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.rag_service import retrieve_context, format_context_for_prompt
from app.tool_executor import execute_client_tool
import app.crud as crud
from typing import List, Optional
import logging
logger = logging.getLogger(__name__)
settings = get_settings()
client = Groq(api_key=settings.GROQ_API_KEY)

FALLBACK_SYSTEM_PROMPT = (
    "You are a helpful customer service assistant. "
    "Keep responses brief and conversational (1-3 sentences). "
    "Be friendly, professional, and helpful."
)

# Fast model reserved for the trivial one-word confirm/cancel classification.
CLASSIFIER_MODEL = "llama-3.1-8b-instant"

# Per-turn bounds protecting the live call from pathological generations:
# cap how many tool calls run, and how much of each result reaches the
# narration prompt (Twilio's webhook budget is ~15s for the whole turn).
MAX_TOOL_CALLS_PER_TURN = 5
TOOL_RESULT_MAX_CHARS = 4000


def _completion(messages: List[dict], tools: Optional[List[dict]] = None, max_tokens: int = 300):
    kwargs = dict(
        model=settings.GROQ_MODEL,
        messages=messages,
        temperature=0.7,
        max_tokens=max_tokens,
    )
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    return client.chat.completions.create(**kwargs)


def _build_tools_param(tools) -> List[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters_schema,
            },
        }
        for t in tools
    ]


def _validate_arguments(schema: dict, arguments: dict) -> List[str]:
    """Validate model-generated tool arguments against the tool's JSON Schema.

    Generic — works for any client-created tool; there is no tool-specific logic
    here. Returns a list of human-readable error messages (empty means valid).
    Never raises: a broken/unusable schema yields no errors rather than blocking
    a live call, so validation can only reject, never crash.
    """
    try:
        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(arguments), key=lambda e: list(e.path))
    except Exception as e:
        logger.warning(f"Argument validation skipped — unusable tool schema: {e}")
        return []
    return [e.message for e in errors]


def _classify_confirmation(user_message: str, tool_name: str, arguments: dict) -> str:
    """Classify the caller's reply to a pending-action read-back.

    Returns CONFIRM, CANCEL, or OTHER. Any failure counts as OTHER — nothing
    executes without an explicit CONFIRM.
    """
    try:
        response = client.chat.completions.create(
            model=CLASSIFIER_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "A phone caller was asked to confirm this action before it is performed: "
                        f"'{tool_name}' with details {json.dumps(arguments)}. "
                        "Classify the caller's reply. Respond with exactly one word:\n"
                        "CONFIRM - they clearly agree to proceed\n"
                        "CANCEL - they decline or want to stop\n"
                        "OTHER - they want to change details or said something unrelated"
                    ),
                },
                {"role": "user", "content": user_message},
            ],
            temperature=0,
            max_tokens=5,
        )
        verdict = response.choices[0].message.content.strip().upper()
        if verdict.startswith("CONFIRM"):
            return "CONFIRM"
        if verdict.startswith("CANCEL"):
            return "CANCEL"
        return "OTHER"
    except Exception as e:
        logger.warning(f"Confirmation classifier failed ({e}); treating reply as OTHER.")
        return "OTHER"


async def _execute_batch_and_narrate(
    db: AsyncSession,
    call_id: int,
    calls: List[dict],  # {"tool_call_id", "tool", "arguments", optional "precomputed"}
    messages: List[dict],
) -> str:
    """Execute tool calls concurrently, log each, and narrate once.

    The Groq protocol requires a tool response for every tool_call_id echoed in
    the assistant message, so every call gets a result — none are dropped.
    HTTP executions run concurrently (latency bounded by the slowest endpoint,
    not the sum — the voice turn has a ~15s Twilio budget). DB logging stays
    sequential: an AsyncSession must not be used concurrently. A call carrying
    "precomputed" (e.g. a validation failure) skips HTTP but is still logged
    and still answers its tool_call_id.
    """
    async def _run(c):
        if "precomputed" in c:
            return c["precomputed"]
        return await execute_client_tool(c["tool"], c["arguments"])

    results = await asyncio.gather(*(_run(c) for c in calls))

    for c, (success, result) in zip(calls, results):
        await crud.log_tool_call(
            db, call_id=call_id, tool_id=c["tool"].id, arguments=c["arguments"],
            response=result, success=success,
            error_message=None if success else result.get("error"),
        )

    followup = messages + [{
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": c["tool_call_id"],
            "type": "function",
            "function": {"name": c["tool"].name, "arguments": json.dumps(c["arguments"])},
        } for c in calls],
    }]
    for c, (success, result) in zip(calls, results):
        payload = json.dumps(result)
        if len(payload) > TOOL_RESULT_MAX_CHARS:
            payload = payload[:TOOL_RESULT_MAX_CHARS] + " …[truncated]"
        followup.append({"role": "tool", "tool_call_id": c["tool_call_id"], "content": payload})

    failed = sum(1 for ok, _ in results if not ok)
    if failed == len(calls):
        followup.append({
            "role": "system",
            "content": (
                "The action failed. Apologize briefly, do NOT read out technical details, "
                "and offer an alternative such as taking the caller's information manually."
            ),
        })
    elif failed:
        followup.append({
            "role": "system",
            "content": (
                "Some lookups failed. Answer using the results that succeeded, briefly "
                "mention what you could not check, and do NOT read out technical details."
            ),
        })
    if len(calls) > 1:
        followup.append({
            "role": "system",
            "content": (
                "Combine all tool results into one clear spoken answer for a phone caller. "
                "Give the concrete specifics the caller asked for (names, prices), grouped "
                "naturally — not a vague summary. Also mention anything that came back "
                "unavailable or failed. End by asking which option the caller prefers."
            ),
        })
    response = _completion(followup)
    return response.choices[0].message.content


async def _execute_and_narrate(
    db: AsyncSession,
    call_id: int,
    tool,
    arguments: dict,
    messages: List[dict],
    tool_call_id: str,
) -> str:
    """Single-call wrapper — used by the confirmed-pending path."""
    return await _execute_batch_and_narrate(
        db, call_id,
        [{"tool_call_id": tool_call_id, "tool": tool, "arguments": arguments}],
        messages,
    )


async def get_ai_response(
    user_message: str,
    client_id: int,
    db: AsyncSession,
    conversation_history: List[dict] = None,
    call_id: Optional[int] = None
) -> str:
    tenant = await crud.get_client(db, client_id)
    if tenant:
        base_prompt = tenant.system_prompt
    else:
        # Shouldn't happen given the NOT NULL FK, but don't crash a live call over it.
        logger.error(f"Client {client_id} not found; falling back to default system prompt.")
        base_prompt = FALLBACK_SYSTEM_PROMPT

    # Retrieve relevant context from knowledge base, scoped to this client
    chunks = retrieve_context(user_message, client_id=client_id)
    context = format_context_for_prompt(chunks)

    # Build system prompt — inject RAG context if available
    if context:
        system_prompt = (
            f"{base_prompt}\n\n"
            "Use the following information to answer the user's question accurately. "
            "If the answer isn't in the provided information, use your general knowledge "
            "but stay within your role as a customer service agent.\n\n"
            f"{context}"
        )
        logger.info(f"RAG context injected ({len(chunks)} chunks)")
    else:
        system_prompt = base_prompt
        logger.info("No RAG context found, using base prompt.")

    messages = [{"role": "system", "content": system_prompt}]

    if conversation_history:
        messages.extend(conversation_history)

    messages.append({"role": "user", "content": user_message})

    # ── Resolve a pending tool call awaiting the caller's confirmation ──
    # Whenever an unresolved pending action is discarded, an audit row records
    # why (stale/superseded/abandoned) so a client can reconstruct the call.
    discarded_pending = None  # (tool_id, arguments) discarded on an OTHER verdict

    async def _log_discarded(reason: str):
        if discarded_pending:
            d_tool_id, d_arguments = discarded_pending
            await crud.log_tool_call(
                db, call_id=call_id, tool_id=d_tool_id, arguments=d_arguments,
                response=None, success=False, error_message=reason,
            )

    if call_id is not None:
        pending = await crud.get_pending_tool_call(db, call_id)
        if pending:
            tool = await crud.get_tool_by_id(db, pending.tool_id)
            if not tool or not tool.is_active:
                logger.warning(f"Pending tool {pending.tool_id} no longer exists/active; discarding.")
                stale_arguments = pending.arguments
                await crud.delete_pending_tool_call(db, call_id)
                if tool:
                    # Only loggable while the tool row still exists — the
                    # tool_call_logs FK requires it.
                    await crud.log_tool_call(
                        db, call_id=call_id, tool_id=tool.id, arguments=stale_arguments,
                        response=None, success=False,
                        error_message="stale tool no longer active",
                    )
            else:
                verdict = _classify_confirmation(user_message, tool.name, pending.arguments)
                logger.info(f"Pending '{tool.name}' confirmation verdict: {verdict}")

                if verdict == "CONFIRM":
                    arguments = pending.arguments
                    await crud.delete_pending_tool_call(db, call_id)
                    return await _execute_and_narrate(
                        db, call_id, tool, arguments, messages,
                        tool_call_id=f"confirmed_{pending.id}",
                    )

                if verdict == "CANCEL":
                    await crud.delete_pending_tool_call(db, call_id)
                    await crud.log_tool_call(
                        db, call_id=call_id, tool_id=tool.id, arguments=pending.arguments,
                        response=None, success=False, error_message="cancelled by caller",
                    )
                    cancel_messages = messages + [{
                        "role": "system",
                        "content": (
                            f"The caller declined the pending action '{tool.name}'. Do not perform it. "
                            "Acknowledge the cancellation briefly and offer to help another way."
                        ),
                    }]
                    response = _completion(cancel_messages)
                    return response.choices[0].message.content

                # OTHER: caller changed details or moved on — discard the stale
                # pending action and fall through; the model can propose a fresh
                # tool call with amended arguments (which is confirmed again).
                # Logged further down, once we know whether it was superseded
                # by a new proposal or simply abandoned.
                discarded_pending = (tool.id, pending.arguments)
                await crud.delete_pending_tool_call(db, call_id)

    # ── Normal flow, with the client's tools offered to the model ──
    tools_param = None
    if call_id is not None:
        active_tools = await crud.get_active_tools(db, client_id)
        if active_tools:
            tools_param = _build_tools_param(active_tools)
            # Constrain how the model fills tool arguments. Added only when tools
            # are actually offered, so it never affects plain conversational turns.
            messages.append({
                "role": "system",
                "content": (
                    "When calling a tool:\n"
                    "- Include only information explicitly provided by the user.\n"
                    "- Never invent, assume, or default optional parameter values.\n"
                    "- Omit optional parameters when the user has not provided them.\n"
                    "- If required information is missing, ask a follow-up question.\n"
                    "- If an optional filter parameter was not specified by the caller, make "
                    "ONE call omitting that parameter — never one call per possible value.\n"
                    "- Prefer a single tool call per turn."
                ),
            })

    # Groq validates generated tool arguments against the schema server-side;
    # a malformed generation (e.g. "4" instead of 4) surfaces as a 400 with
    # code "tool_use_failed" rather than a completion. Retry once — sampling
    # usually fixes it — then degrade to a plain reply instead of crashing
    # the live call.
    try:
        response = _completion(messages, tools=tools_param)
    except BadRequestError as e:
        if not (tools_param and "tool_use_failed" in str(e)):
            raise
        logger.warning(f"Tool-call generation failed Groq's schema validation; retrying once. ({e})")
        try:
            response = _completion(messages, tools=tools_param)
        except BadRequestError:
            logger.warning("Retry also failed schema validation; answering without tools.")
            response = _completion(messages)
    message = response.choices[0].message

    # TEMP DEBUG: diagnose tool-call arguments vs. what the caller actually asked
    # for (e.g. invented optional parameters, or multiple calls when one is used).
    # Remove once the optional-parameter issue is resolved.
    if message.tool_calls:
        logger.info("=== TOOL CALL DEBUG ===")
        logger.info(f"User: {user_message!r}")
        logger.info(f"Number of tool calls: {len(message.tool_calls)}")
        for i, tc in enumerate(message.tool_calls):
            logger.info(f"Tool #{i + 1}: name={tc.function.name}, args={tc.function.arguments}")
        logger.info("=== END TOOL CALL DEBUG ===")

    if not message.tool_calls:
        await _log_discarded("abandoned — caller reply not a confirmation")
        return message.content

    # Resolve every generated call: client-scoped tool lookup, parsed args,
    # schema validation. From here on nothing is silently dropped — a call
    # either executes, gets a per-id failure result, or leaves an audit row.
    tool_calls = message.tool_calls[:MAX_TOOL_CALLS_PER_TURN]
    if len(message.tool_calls) > MAX_TOOL_CALLS_PER_TURN:
        logger.warning(
            f"Model requested {len(message.tool_calls)} tool calls; capping at {MAX_TOOL_CALLS_PER_TURN}."
        )
        # Audit the sliced-off calls too — same "nothing silently dropped"
        # standard as the rest of the flow. Unknown tool names can't be audited
        # (tool_call_logs.tool_id is a non-nullable FK) and are app-logged only.
        for tc in message.tool_calls[MAX_TOOL_CALLS_PER_TURN:]:
            excess_tool = await crud.get_tool_by_name(db, client_id, tc.function.name)
            if not excess_tool:
                logger.warning(f"Over-cap call to unknown tool '{tc.function.name}' dropped (no audit row).")
                continue
            try:
                excess_args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                excess_args = {}
            await crud.log_tool_call(
                db, call_id=call_id, tool_id=excess_tool.id, arguments=excess_args,
                response=None, success=False,
                error_message=f"dropped — exceeded per-turn tool call cap ({MAX_TOOL_CALLS_PER_TURN})",
            )

    resolved = []
    for tc in tool_calls:
        tool = await crud.get_tool_by_name(db, client_id, tc.function.name)
        if not tool:
            logger.warning(f"Model called unknown tool '{tc.function.name}' for client {client_id}.")
        try:
            arguments = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            logger.warning(f"Unparseable tool arguments for '{tc.function.name}': {tc.function.arguments!r}")
            arguments = {}
        errors = _validate_arguments(tool.parameters_schema, arguments) if tool else []
        resolved.append({
            "tool_call_id": tc.id, "tool": tool, "arguments": arguments, "errors": errors,
        })

    # Unknown-tool calls can't be executed or audited (tool_call_logs needs a
    # tool FK); they were logged above and are simply not echoed to the model.
    known = [r for r in resolved if r["tool"]]
    if not known:
        await _log_discarded("abandoned — caller reply not a confirmation")
        retry = _completion(messages)  # no tools — plain conversational reply
        return retry.choices[0].message.content

    await _log_discarded("superseded by amended request")

    # Every call invalid → don't execute anything; ask a follow-up instead.
    # (This is also the unchanged single-call validation-failure behavior.)
    if all(r["errors"] for r in known):
        joined = "; ".join(e for r in known for e in r["errors"])
        logger.warning(f"All tool calls failed argument validation: {joined}")
        for r in known:
            await crud.log_tool_call(
                db, call_id=call_id, tool_id=r["tool"].id, arguments=r["arguments"],
                response=None, success=False,
                error_message="argument validation failed: " + "; ".join(r["errors"]),
            )
        clarify_messages = messages + [{
            "role": "system",
            "content": (
                f"The information collected for the action '{known[0]['tool'].name}' is incomplete or invalid: "
                + joined + ". "
                "Do NOT claim the action was performed. Ask the caller a brief, natural spoken "
                "follow-up question to get the missing or corrected details."
            ),
        }]
        clarify = _completion(clarify_messages)
        return clarify.choices[0].message.content

    # One pending confirmation per call is a deliberate voice-flow constraint
    # (pending_tool_calls.call_id is UNIQUE): a caller can only hear and confirm
    # one action at a time. If any valid call needs confirmation, keep the
    # single-action path. Dropping the other calls (including read-only ones) is
    # intentional: the readback stays single-purpose so the caller's next reply
    # classifies cleanly as confirm/cancel, and the drops are audited below.
    confirm = [r for r in known if r["tool"].requires_confirmation and not r["errors"]]
    if confirm:
        chosen = confirm[0]
        for r in known:
            if r is not chosen:
                await crud.log_tool_call(
                    db, call_id=call_id, tool_id=r["tool"].id, arguments=r["arguments"],
                    response=None, success=False,
                    error_message="dropped — one confirmable action per turn (voice flow)",
                )
        tool, arguments = chosen["tool"], chosen["arguments"]
        await crud.create_pending_tool_call(db, call_id=call_id, tool_id=tool.id, arguments=arguments)
        readback_messages = messages + [{
            "role": "system",
            "content": (
                f"You are about to perform the action '{tool.name}' ({tool.description}) "
                f"with these details: {json.dumps(arguments)}. "
                "Read the details back to the caller in one or two natural spoken sentences "
                "and ask them to confirm before proceeding. "
                "Do not claim the action has been performed yet."
            ),
        }]
        readback = _completion(readback_messages)
        return readback.choices[0].message.content

    # No confirmations involved: execute every valid call concurrently. Calls
    # that failed validation still answer their tool_call_id with a failure
    # result so the model can explain or re-ask naturally.
    batch = []
    for r in known:
        item = {"tool_call_id": r["tool_call_id"], "tool": r["tool"], "arguments": r["arguments"]}
        if r["errors"]:
            logger.warning(f"Tool '{r['tool'].name}' arguments failed schema validation: {r['errors']}")
            item["precomputed"] = (False, {"error": "invalid arguments: " + "; ".join(r["errors"])})
        batch.append(item)
    return await _execute_batch_and_narrate(db, call_id, batch, messages)
