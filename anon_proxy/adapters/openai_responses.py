from __future__ import annotations

from anon_proxy.masker import Masker


def unmask_responses_value(value, masker: Masker):
    """Unmask a Responses-shaped value, treating `arguments` as JSON text."""
    if isinstance(value, str):
        return masker.unmask(value)
    if isinstance(value, list):
        return [unmask_responses_value(item, masker) for item in value]
    if isinstance(value, dict):
        return {
            key: (
                masker.unmask_json(item)
                if key == "arguments" and isinstance(item, str)
                else unmask_responses_value(item, masker)
            )
            for key, item in value.items()
        }
    return value
