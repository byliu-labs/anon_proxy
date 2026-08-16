from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable

from anon_proxy.adapters._streaming import split_at_last_open
from anon_proxy.masker import Masker


async def transform_stream(
    upstream_bytes: AsyncIterator[bytes],
    masker: Masker,
    *,
    on_substitution: Callable[[str, str], None] | None = None,
    on_usage: Callable[[dict], None] | None = None,
) -> AsyncIterator[bytes]:
    """Unmask masked payloads in an OpenAI SSE stream."""
    tool_call_buffers: dict[int, str] = {}
    responses_argument_buffers: dict[str, str] = {}
    content_buffer = [""]
    responses_text_buffer = [""]
    raw = b""

    async for chunk in upstream_bytes:
        raw += chunk
        while b"\n\n" in raw:
            event_bytes, raw = raw.split(b"\n\n", 1)
            event_type, data_str = _parse_sse(event_bytes)

            if data_str == "[DONE]":
                for out_event, out_data in _flush_openai_buffers(
                    masker,
                    tool_call_buffers,
                    content_buffer,
                    responses_text_buffer,
                    responses_argument_buffers,
                    on_substitution,
                ):
                    yield _serialize_sse(out_event, out_data)
                yield _serialize_sse(event_type, data_str)
                continue

            for out_event, out_data in _transform_event(
                event_type,
                data_str,
                masker,
                tool_call_buffers,
                content_buffer,
                responses_text_buffer,
                responses_argument_buffers,
                on_substitution,
                on_usage,
            ):
                yield _serialize_sse(out_event, out_data)

    for out_event, out_data in _flush_openai_buffers(
        masker,
        tool_call_buffers,
        content_buffer,
        responses_text_buffer,
        responses_argument_buffers,
        on_substitution,
    ):
        yield _serialize_sse(out_event, out_data)

    if raw.strip():
        yield raw


def _parse_sse(event_bytes: bytes) -> tuple[str | None, str | None]:
    event_type: str | None = None
    data_parts: list[str] = []
    for line in event_bytes.decode("utf-8", errors="replace").splitlines():
        if line.startswith(":") or not line:
            continue
        if line.startswith("event:"):
            event_type = line[len("event:") :].strip()
        elif line.startswith("data:"):
            chunk = line[len("data:") :]
            if chunk.startswith(" "):
                chunk = chunk[1:]
            data_parts.append(chunk)
    data = "\n".join(data_parts) if data_parts else None
    return event_type, data


def _serialize_sse(event_type: str | None, data: str | None) -> bytes:
    lines: list[str] = []
    if event_type:
        lines.append(f"event: {event_type}")
    if data is not None:
        lines.append(f"data: {data}")
    return ("\n".join(lines) + "\n\n").encode("utf-8")


def _transform_event(
    event_type: str | None,
    data_str: str | None,
    masker: Masker,
    tool_call_buffers: dict[int, str],
    content_buffer: list[str],
    responses_text_buffer: list[str],
    responses_argument_buffers: dict[str, str],
    on_substitution: Callable[[str, str], None] | None,
    on_usage: Callable[[dict], None] | None,
):
    if data_str is None or data_str == "[DONE]":
        yield event_type, data_str
        return

    try:
        data = json.loads(data_str)
    except json.JSONDecodeError:
        yield event_type, data_str
        return

    usage = data.get("usage")
    if isinstance(usage, dict) and on_usage is not None:
        on_usage(usage)

    response_type = data.get("type") or event_type
    if isinstance(response_type, str) and response_type.startswith("response."):
        yield from _transform_responses_event(
            event_type,
            data,
            response_type,
            masker,
            responses_text_buffer,
            responses_argument_buffers,
            on_substitution,
        )
        return

    choices = data.get("choices", [])
    if not isinstance(choices, list):
        yield event_type, data_str
        return

    transformed = False
    for choice in choices:
        delta = choice.get("delta", {})
        if not isinstance(delta, dict):
            continue

        content = delta.get("content")
        if isinstance(content, str):
            content_buffer[0] += content
            emittable, remainder = split_at_last_open(content_buffer[0])
            content_buffer[0] = remainder
            if emittable:
                unmasked = masker.unmask(emittable)
                if on_substitution and emittable != unmasked:
                    on_substitution(emittable, unmasked)
                choice["delta"]["content"] = unmasked
                yield event_type, json.dumps(data)
            transformed = True
            break

        tool_calls = delta.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            emitted = _transform_tool_calls(
                tool_calls,
                tool_call_buffers,
                masker,
                on_substitution,
            )
            if emitted:
                yield event_type, json.dumps(data)
            transformed = True
            break

        if content is None:
            if content_buffer[0]:
                buffered = content_buffer[0]
                unmasked = masker.unmask(buffered)
                if on_substitution and buffered != unmasked:
                    on_substitution(buffered, unmasked)
                choice["delta"]["content"] = unmasked
                content_buffer[0] = ""
                yield event_type, json.dumps(data)
                transformed = True
                break
            yield event_type, json.dumps(data)
            transformed = True
            break

    if not transformed:
        yield event_type, data_str


def _transform_tool_calls(
    tool_calls: list,
    tool_call_buffers: dict[int, str],
    masker: Masker,
    on_substitution: Callable[[str, str], None] | None,
) -> bool:
    emitted = False
    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            continue
        index = tool_call.get("index", 0)
        function = tool_call.get("function", {})
        if not isinstance(function, dict):
            continue
        args_delta = function.get("arguments", "")
        if not args_delta:
            emitted = True
        elif isinstance(args_delta, str):
            buffered = tool_call_buffers.get(index, "") + args_delta
            tool_call_buffers[index] = buffered
            if _is_complete_json(buffered):
                unmasked = masker.unmask_json(buffered)
                if on_substitution and buffered != unmasked:
                    on_substitution(buffered, unmasked)
                function["arguments"] = unmasked
                tool_call_buffers[index] = ""
            else:
                function["arguments"] = ""
            emitted = True
    return emitted


def _is_complete_json(s: str) -> bool:
    try:
        json.loads(s)
        return True
    except json.JSONDecodeError:
        return False


def _flush_openai_buffers(
    masker: Masker,
    tool_call_buffers: dict[int, str],
    content_buffer: list[str],
    responses_text_buffer: list[str],
    responses_argument_buffers: dict[str, str],
    on_substitution: Callable[[str, str], None] | None,
):
    if content_buffer[0]:
        buffered = content_buffer[0]
        unmasked = masker.unmask(buffered)
        if on_substitution and buffered != unmasked:
            on_substitution(buffered, unmasked)
        yield None, json.dumps({"choices": [{"delta": {"content": unmasked}}]})
        content_buffer[0] = ""

    for index, buffered in list(tool_call_buffers.items()):
        if not buffered:
            continue
        unmasked = masker.unmask_json(buffered)
        if on_substitution and buffered != unmasked:
            on_substitution(buffered, unmasked)
        yield (
            None,
            json.dumps(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": index,
                                        "function": {"arguments": unmasked},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ),
        )
        tool_call_buffers[index] = ""

    if responses_text_buffer[0]:
        buffered = responses_text_buffer[0]
        unmasked = masker.unmask(buffered)
        if on_substitution and buffered != unmasked:
            on_substitution(buffered, unmasked)
        yield (
            "response.output_text.delta",
            json.dumps({"type": "response.output_text.delta", "delta": unmasked}),
        )
        responses_text_buffer[0] = ""

    for key, buffered in list(responses_argument_buffers.items()):
        if not buffered:
            continue
        unmasked = masker.unmask_json(buffered)
        if on_substitution and buffered != unmasked:
            on_substitution(buffered, unmasked)
        yield (
            "response.function_call_arguments.delta",
            json.dumps(
                {
                    "type": "response.function_call_arguments.delta",
                    "item_id": key,
                    "delta": unmasked,
                }
            ),
        )
        responses_argument_buffers[key] = ""


def _transform_responses_event(
    event_type: str | None,
    data: dict,
    response_type: str,
    masker: Masker,
    text_buffer: list[str],
    argument_buffers: dict[str, str],
    on_substitution: Callable[[str, str], None] | None,
):
    if response_type == "response.output_text.delta":
        delta = data.get("delta")
        if not isinstance(delta, str):
            yield event_type, json.dumps(data)
            return
        text_buffer[0] += delta
        emittable, remainder = split_at_last_open(text_buffer[0])
        text_buffer[0] = remainder
        if emittable:
            unmasked = masker.unmask(emittable)
            if on_substitution and emittable != unmasked:
                on_substitution(emittable, unmasked)
            yield event_type, json.dumps({**data, "delta": unmasked})
        return

    if response_type == "response.function_call_arguments.delta":
        delta = data.get("delta")
        if not isinstance(delta, str):
            yield event_type, json.dumps(data)
            return
        key = str(data.get("item_id") or data.get("call_id") or "0")
        buffered = argument_buffers.get(key, "") + delta
        argument_buffers[key] = buffered
        if _is_complete_json(buffered):
            unmasked = masker.unmask_json(buffered)
            if on_substitution and buffered != unmasked:
                on_substitution(buffered, unmasked)
            argument_buffers[key] = ""
            yield event_type, json.dumps({**data, "delta": unmasked})
        return

    yield event_type, json.dumps(_walk_strings(data, masker.unmask))


def _walk_strings(value, transform):
    if isinstance(value, str):
        return transform(value)
    if isinstance(value, dict):
        return {k: _walk_strings(v, transform) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk_strings(v, transform) for v in value]
    return value
