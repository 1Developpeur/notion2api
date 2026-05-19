from __future__ import annotations


def normalize_model_id(model: str | None) -> str | None:
    if not model:
        return model

    if model.startswith("custom:"):
        return model.removeprefix("custom:")

    return model
