"""
Tract: infrastructure derived from the program that runs on it.

You declare what to expose; Tract computes what must be provisioned from the
capability footprint of the code behind it. Exposing a function whose call
graph needs storage, with no storage declared, is a compile error rather than a
deployment that fails at the first request.
"""

__version__ = "0.1.0"

from .lang import (  # noqa: E402
    AMBIENT_EFFECTS,
    LANGUAGE_VERSION,
    RESOURCE_KINDS,
    EndpointPlan,
    Exposure,
    Manifest,
    Planner,
    ResourceDecl,
    TractParser,
    parse_tract,
    plan,
)

__all__ = [
    "__version__", "LANGUAGE_VERSION",
    "parse_tract", "plan", "TractParser", "Planner",
    "ResourceDecl", "Exposure", "EndpointPlan", "Manifest",
    "RESOURCE_KINDS", "AMBIENT_EFFECTS",
]
