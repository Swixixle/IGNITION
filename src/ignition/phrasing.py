"""Optional softer wording when plain_language is enabled in config."""

from __future__ import annotations

from ignition.config import IgnitionConfig


def scope_drift_line(cfg: IgnitionConfig) -> str:
    if cfg.plain_language:
        return "Some changes are outside the area you listed for this session."
    return "Scope drift: some changes are outside declared scope."


def risk_header(cfg: IgnitionConfig) -> str:
    if cfg.plain_language:
        return "Things to be aware of:"
    return "Risk flags:"


def primary_rec_label(cfg: IgnitionConfig) -> str:
    if cfg.plain_language:
        return "Suggested next step"
    return "Primary"
