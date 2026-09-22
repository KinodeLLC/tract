"""
tract, infrastructure that comes off the program running on it.

you declare what to expose and what has to be provisioned gets worked out from
the effects the code behind it can reach. exposing a function whose call graph
needs storage with no storage declared is a compile error instead of a deploy
that dies on the first request.
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
