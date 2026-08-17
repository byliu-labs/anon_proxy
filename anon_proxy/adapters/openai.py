"""OpenAI Chat Completions API request/response transforms.

OpenAI format uses:
- Request: messages with role/content, functions/tools
- Response: choices with message content
- Streaming: SSE with delta content

Masked on outbound: messages content, function arguments, tool call inputs.
Unmasked on inbound: message content, function arguments, tool call outputs.
"""

from __future__ import annotations

import json

from anon_proxy.adapters.openai_streaming import (
    _is_complete_json as _is_complete_json,
    transform_stream as transform_stream,
)
from anon_proxy.adapters.openai_responses import unmask_responses_value
from anon_proxy.masker import Masker
from anon_proxy.policy import Policy, mask_body


OPENAI_POLICY = Policy(
    pass_keys=frozenset(
        {
            "model",
            "role",
            "type",
            "id",
            "name",
            "tool_call_id",
            "finish_reason",
            "logprobs",
            "response_format",
            "tool_choice",
            "user",
        }
    ),
    pass_paths=frozenset({("tools",), ("functions",), ("instructions",)}),
    pass_block_types=frozenset(),
    pass_block_subtrees={"image_url": "image_url"},
    json_string_keys=frozenset({"arguments"}),
)


def mask_request(body: dict, masker: Masker) -> dict:
    """Return a copy of an OpenAI request body with PII masked."""
    return mask_body(body, masker, OPENAI_POLICY)


def inject_system(body: dict, prompt: str) -> dict:
    """Prepend `prompt` as system instruction in the OpenAI request.

    If the first message is a `system` (or `developer`) message, we merge our
    text into the front of its content. Otherwise, we insert a new `system`
    message at index 0. Either way the injected text comes first so the model
    sees the placeholder explanation before any client-supplied instructions.
    """
    result = dict(body)
    if "messages" not in body:
        if "input" in body:
            existing = body.get("instructions")
            if isinstance(existing, str) and existing:
                result["instructions"] = f"{prompt}\n\n{existing}"
            else:
                result["instructions"] = prompt
        return result
    messages = list(body.get("messages") or [])
    if (
        messages
        and isinstance(messages[0], dict)
        and messages[0].get("role") in ("system", "developer")
    ):
        first = dict(messages[0])
        content = first.get("content")
        if isinstance(content, str):
            first["content"] = f"{prompt}\n\n{content}"
        elif isinstance(content, list):
            first["content"] = [{"type": "text", "text": prompt}, *content]
        else:
            first["content"] = prompt
        messages[0] = first
    else:
        messages.insert(0, {"role": "system", "content": prompt})
    result["messages"] = messages
    return result


def unmask_response(body: dict, masker: Masker) -> dict:
    """Return a copy of a non-streaming response with text unmasked."""
    result = dict(body)
    choices = body.get("choices")
    if isinstance(choices, list):
        result["choices"] = [_unmask_choice(c, masker) for c in choices]
    output_text = body.get("output_text")
    if isinstance(output_text, str):
        result["output_text"] = masker.unmask(output_text)
    output = body.get("output")
    if isinstance(output, list):
        result["output"] = unmask_responses_value(output, masker)
    return result


def _unmask_choice(choice: dict, masker: Masker) -> dict:
    """Unmask a response choice."""
    result = dict(choice)
    message = choice.get("message")
    if isinstance(message, dict):
        result["message"] = _unmask_message(message, masker)
    return result


def _unmask_message(message: dict, masker: Masker) -> dict:
    """Unmask a response message."""
    if not isinstance(message, dict):
        return message

    result = dict(message)

    # Unmask content
    content = message.get("content")
    if isinstance(content, str):
        result["content"] = masker.unmask(content)
    elif isinstance(content, list):
        result["content"] = [_unmask_content_item(c, masker) for c in content]

    # Unmask tool calls
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        result["tool_calls"] = [_unmask_tool_call(tc, masker) for tc in tool_calls]

    return result


def _unmask_content_item(item: dict, masker: Masker) -> dict:
    """Unmask a content item."""
    if item.get("type") == "text" and isinstance(item.get("text"), str):
        return {**item, "text": masker.unmask(item["text"])}
    return item


def _unmask_tool_call(tool_call: dict, masker: Masker) -> dict:
    """Unmask a tool call."""
    result = dict(tool_call)
    function = tool_call.get("function", {})
    if isinstance(function, dict):
        args = function.get("arguments")
        if isinstance(args, str):
            try:
                args_obj = json.loads(args)
                unmasked = _walk_strings(args_obj, masker.unmask)
                result["function"] = {**function, "arguments": json.dumps(unmasked)}
            except json.JSONDecodeError:
                result["function"] = {**function, "arguments": masker.unmask(args)}
        elif isinstance(args, dict):
            result["function"] = {
                **function,
                "arguments": _walk_strings(args, masker.unmask),
            }
    return result


def _walk_strings(value, transform):
    """Apply `transform` to every string leaf of a JSON-shaped value."""
    if isinstance(value, str):
        return transform(value)
    if isinstance(value, dict):
        return {k: _walk_strings(v, transform) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk_strings(v, transform) for v in value]
    return value
