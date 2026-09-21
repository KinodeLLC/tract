"""
Tract: infrastructure derived from the program that runs on it.

Ordinary infrastructure-as-code describes what to provision. Tract describes
what to *expose*, and derives what must be provisioned from the capability
footprint of the code behind it. The two halves of a deployment -- the code and
the infrastructure it needs -- stop being two documents that have to be kept in
agreement.

What that buys, concretely:

  * Exposing a function whose call graph writes to storage, with no storage
    resource declared, is a compile error naming the capability and the
    function that needs it. The usual version of this failure is a deployment
    that succeeds and then fails at the first request.

  * Declaring a resource nothing needs is reported too. Unused infrastructure
    is cost and attack surface that no one is watching.

  * The capability footprint of every endpoint is computed, not declared, so
    it cannot be understated. An endpoint's stated permissions and its actual
    reach are the same number by construction.

  * The manifest is generated from the program, so a change to the code that
    widens what it touches changes the manifest in the same commit, where a
    reviewer or a promotion gate will see it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from canon import ast as A
from canon import types as TY
from canon.diagnostics import Bag, Repair, Span
from canon.lexer import Lexer, T
from canon.parser import Parser


LANGUAGE_VERSION = "0.1"

# What each resource kind is able to satisfy. An endpoint may only reach
# effects that one of the declared resources provides.
RESOURCE_KINDS = {
    "HttpService": {"provides": set(), "hosts": True,
                    "doc": "An HTTP endpoint surface."},
    "Table": {"provides": {"store", "db", "table", "ledger"}, "hosts": False,
              "doc": "Durable record storage."},
    "Queue": {"provides": {"queue", "events", "workflow"}, "hosts": False,
              "doc": "Asynchronous message delivery."},
    "Cache": {"provides": {"cache"}, "hosts": False,
              "doc": "Ephemeral keyed storage."},
    "ObjectStore": {"provides": {"blobs", "files", "objects"}, "hosts": False,
                    "doc": "Large object storage."},
    "Mailer": {"provides": {"mail", "mailer", "notify"}, "hosts": False,
               "doc": "Outbound message delivery."},
    "ModelAccess": {"provides": {"model"}, "hosts": False,
                    "doc": "Access to inference models."},
    "Secret": {"provides": {"secrets"}, "hosts": False,
               "doc": "Credential storage."},
    "Schedule": {"provides": {"time", "timer"}, "hosts": False,
                 "doc": "Timed invocation."},
}

# Effects every deployment may perform without a dedicated resource.
AMBIENT_EFFECTS = {"log", "audit", "random"}


@dataclass
class Exposure:
    function: str = ""
    path: str = ""
    method: str = "POST"
    public: bool = False
    span: Span = field(default_factory=Span.unknown)


@dataclass
class ResourceDecl:
    name: str = ""
    kind: str = ""
    region: str = ""
    environment: str = ""
    scale_to: int = 0
    retention_days: int = 0
    schema: str = ""
    key: str = ""
    exposures: list = field(default_factory=list)
    consumers: list = field(default_factory=list)
    quotas: dict = field(default_factory=dict)
    money_budget: Optional[Decimal] = None
    depends: list = field(default_factory=list)
    intent: str = ""
    doc: str = ""
    span: Span = field(default_factory=Span.unknown)

    def provides(self) -> set:
        return set(RESOURCE_KINDS.get(self.kind, {}).get("provides", set()))


@dataclass
class EndpointPlan:
    function: str
    path: str
    method: str
    public: bool
    capabilities: list = field(default_factory=list)
    classifications: list = field(default_factory=list)
    models: list = field(default_factory=list)
    satisfied_by: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"function": self.function, "path": self.path,
                "method": self.method, "public": self.public,
                "capabilities": self.capabilities,
                "data_classifications": self.classifications,
                "models": self.models, "satisfied_by": self.satisfied_by}


@dataclass
class Manifest:
    module: str = ""
    resources: list = field(default_factory=list)
    endpoints: list = field(default_factory=list)
    unused_resources: list = field(default_factory=list)
    total_money_budget: Decimal = field(default_factory=lambda: Decimal(0))

    def to_json(self) -> dict:
        return {
            "module": self.module,
            "resources": [{"name": r.name, "kind": r.kind, "region": r.region,
                           "environment": r.environment,
                           "scale_to": r.scale_to,
                           "retention_days": r.retention_days,
                           "schema": r.schema, "key": r.key,
                           "quotas": r.quotas,
                           "budget": str(r.money_budget)
                           if r.money_budget is not None else None,
                           "depends": r.depends}
                          for r in self.resources],
            "endpoints": [e.to_json() for e in self.endpoints],
            "unused_resources": self.unused_resources,
            "total_budget": str(self.total_money_budget),
        }

    def render(self) -> str:
        lines = [f"deployment manifest for {self.module}"]
        for r in self.resources:
            bits = [r.kind]
            if r.region:
                bits.append(r.region)
            if r.scale_to:
                bits.append(f"scale {r.scale_to}")
            if r.money_budget is not None:
                bits.append(f"budget {r.money_budget}")
            lines.append(f"  resource {r.name}: {', '.join(bits)}")
        for e in self.endpoints:
            lines.append(f"  {e.method} {e.path} -> {e.function}")
            if e.capabilities:
                lines.append(f"      needs {', '.join(e.capabilities)}")
            if e.classifications:
                lines.append(f"      touches {', '.join(e.classifications)}")
        if self.unused_resources:
            lines.append(f"  unused: {', '.join(self.unused_resources)}")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------

class TractParser(Parser):
    def __init__(self, tokens, source="", filename="<memory>", bag=None):
        super().__init__(tokens, source, filename, bag, language="tract")
        self.resources: list = []

    def parse_decl(self):
        doc = self.skip_docs()
        if self.at_ctx("resource") and self.at(1).kind == T.NAME:
            self.resources.append(self.parse_resource(doc))
            return None
        for fn, kw in ((self.parse_fn, "fn"), (self.parse_record, "record"),
                       (self.parse_enum, "enum"), (self.parse_alias, "alias"),
                       (self.parse_effect, "effect"), (self.parse_const, "const"),
                       (self.parse_test, "test")):
            if self.cur.is_kw(kw):
                return fn(doc)
        return None

    def parse_resource(self, doc: str = "") -> ResourceDecl:
        start = self.next()           # resource
        r = ResourceDecl(doc=doc)
        r.name = self.expect_name("a resource name")
        self.expect_punct(":", "before the resource kind")
        r.kind = self.expect_upper("a resource kind")
        if r.kind not in RESOURCE_KINDS:
            self.err(
                "CANON-E0202", f"unknown resource kind {r.kind!r}", start,
                facts={"kind": r.kind, "known": sorted(RESOURCE_KINDS)},
                repairs=self._near_repairs(r.kind, RESOURCE_KINDS, start.span)
                if hasattr(self, "_near_repairs") else [])

        self.expect_punct("{", "to open the resource body")
        while not self.cur.is_punct("}") and self.cur.kind != T.EOF:
            self.skip_docs()
            if self.cur.is_kw("intent"):
                self.next()
                r.intent = self.parse_text_literal("an intent description")
            elif self.at_ctx("expose"):
                r.exposures.append(self.parse_exposure())
            elif self.at_ctx("consumer", "consumes"):
                self.next()
                r.consumers.append(self.parse_qualified())
            elif self.at_ctx("region"):
                self.next()
                r.region = self.parse_text_literal("a region name")
            elif self.at_ctx("environment"):
                self.next()
                r.environment = self.parse_text_literal("an environment name")
            elif self.at_ctx("scale_to"):
                self.next()
                r.scale_to = self._int("a scale target")
            elif self.at_ctx("retention"):
                self.next()
                r.retention_days = self._int("a retention period in days")
                self.eat_ctx("days")
            elif self.at_ctx("schema"):
                self.next()
                r.schema = self.expect_upper("a schema type name")
            elif self.at_ctx("key"):
                self.next()
                r.key = self.expect_name("a key field name")
            elif self.at_ctx("quota"):
                self.next()
                qname = self.expect_name("a quota name")
                r.quotas[qname] = self._int("a quota value")
            elif self.at_ctx("budget"):
                self.next()
                self.eat_ctx("money")
                if self.cur.kind in (T.INT, T.DEC):
                    r.money_budget = Decimal(str(self.next().payload))
                else:
                    self.err("CANON-E0101", "expected a budget amount")
            elif self.at_ctx("depends"):
                self.next()
                self.eat_ctx("on")
                while self.cur.kind == T.NAME:
                    r.depends.append(self.next().value)
                    if not self.eat_punct(","):
                        break
            else:
                self.err("CANON-E0102",
                         "unknown resource setting",
                         facts={"found": self.cur.value or self.cur.kind,
                                "known": ["expose", "consumer", "region",
                                          "environment", "scale_to",
                                          "retention", "schema", "key",
                                          "quota", "budget", "depends",
                                          "intent"]})
                self.next()
        self.expect_punct("}", "to close the resource body")
        r.span = self.span_from(start)
        return r

    def parse_exposure(self) -> Exposure:
        start = self.next()           # expose
        e = Exposure()
        e.function = self.parse_qualified()
        if self.eat_ctx("at"):
            e.path = self.parse_text_literal("a path")
        if self.eat_ctx("method"):
            e.method = self.parse_text_literal("an HTTP method").upper()
        if self.eat_ctx("public"):
            e.public = True
        if not e.path:
            e.path = "/" + e.function.rsplit(".", 1)[-1]
        e.span = self.span_from(start)
        return e

    def parse_qualified(self) -> str:
        parts = []
        if self.cur.kind in (T.NAME, T.UPPER):
            parts.append(self.next().value)
        else:
            self.err("CANON-E0101", "expected a function name")
            return "unknown"
        while self.cur.is_punct(".") and self.at(1).kind in (T.NAME, T.UPPER):
            self.next()
            parts.append(self.next().value)
        return ".".join(parts)

    def _int(self, what) -> int:
        if self.cur.kind == T.INT:
            return int(self.next().payload)
        self.err("CANON-E0101", f"expected {what}")
        return 0


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------

class Planner:
    """
    Turns resource declarations plus a checked program into a manifest.

    The check that matters is coverage: every effect an exposed function can
    reach must be provided by some declared resource. That is computed from the
    call graph, so it cannot be understated by an author who forgot what a
    helper does.
    """

    def __init__(self, bag: Bag):
        self.bag = bag

    def plan(self, resources: list, cr, module_name: str = "") -> Manifest:
        manifest = Manifest(module=module_name, resources=list(resources))

        provided = {}
        for r in resources:
            for effect in r.provides():
                provided.setdefault(effect, []).append(r.name)

        used_resources = set()

        for r in resources:
            if r.exposures and not RESOURCE_KINDS.get(r.kind, {}).get("hosts"):
                self.bag.error(
                    "CANON-E0301",
                    f"resource {r.name!r} is a {r.kind} and cannot expose "
                    f"endpoints", r.span,
                    facts={"resource": r.name, "kind": r.kind,
                           "hosting_kinds": sorted(
                               k for k, v in RESOURCE_KINDS.items()
                               if v["hosts"])})

            if r.money_budget is not None:
                manifest.total_money_budget += r.money_budget

            for dep in r.depends:
                if not any(other.name == dep for other in resources):
                    self.bag.error(
                        "CANON-E0201",
                        f"resource {r.name!r} depends on {dep!r}, which is "
                        f"not declared", r.span,
                        facts={"resource": r.name, "dependency": dep,
                               "declared": sorted(x.name for x in resources)})
                else:
                    used_resources.add(dep)

            if r.schema and r.schema not in cr.env.types:
                self.bag.error(
                    "CANON-E0202",
                    f"resource {r.name!r} names schema {r.schema!r}, which "
                    f"is not declared", r.span,
                    facts={"resource": r.name, "schema": r.schema})
            elif r.schema and r.key:
                ti = cr.env.types[r.schema]
                names = {f.name for f in getattr(ti.decl, "fields", [])}
                if r.key not in names:
                    self.bag.error(
                        "CANON-E0206",
                        f"{r.schema} has no field {r.key!r} to key on",
                        r.span, facts={"schema": r.schema, "key": r.key,
                                       "available": sorted(names)})

        entry_points = []
        for r in resources:
            for e in r.exposures:
                entry_points.append((r, e, "endpoint"))
            for c in r.consumers:
                entry_points.append(
                    (r, Exposure(function=c, path="", method="CONSUME"),
                     "consumer"))

        for r, e, kind in entry_points:
            fi = cr.env.lookup_fn(e.function.rsplit(".", 1)[-1],
                                  e.function.rsplit(".", 1)[0]
                                  if "." in e.function else "")
            if fi is None:
                self.bag.error(
                    "CANON-E0201",
                    f"{'endpoint' if kind == 'endpoint' else 'consumer'} "
                    f"names {e.function!r}, which is not a function in this "
                    f"program", e.span,
                    facts={"function": e.function,
                           "available": sorted(cr.env.fns)[:40]})
                continue

            used_resources.add(r.name)
            plan = EndpointPlan(
                function=fi.qualname, path=e.path, method=e.method,
                public=e.public,
                capabilities=sorted(fi.transitive),
                classifications=sorted(fi.touches),
                models=sorted(fi.models))

            for key in plan.capabilities:
                effect = key.split(".", 1)[0]
                if effect in AMBIENT_EFFECTS:
                    plan.satisfied_by[key] = "ambient"
                    continue
                providers = provided.get(effect)
                if providers:
                    plan.satisfied_by[key] = providers[0]
                    used_resources.update(providers)
                else:
                    plan.satisfied_by[key] = ""
                    kinds = sorted(k for k, v in RESOURCE_KINDS.items()
                                   if effect in v["provides"])
                    self.bag.error(
                        "CANON-E0403",
                        f"{fi.qualname} needs {key!r} but no declared "
                        f"resource provides it",
                        e.span,
                        facts={"function": fi.qualname, "capability": key,
                               "effect": effect,
                               "resource_kinds_that_provide_it": kinds,
                               "declared": sorted(
                                   {x.kind for x in resources})},
                        repairs=[Repair(
                            "manual",
                            f"declare a resource that provides {effect!r}",
                            f"resource {effect}_store: "
                            f"{kinds[0] if kinds else 'Table'} {{ }}",
                            e.span, 0.6)] if kinds else [],
                        notes=["The capability comes from the function's call "
                               "graph, not from a declaration, so this is "
                               "what the endpoint will actually try to do."])

            if plan.public and plan.classifications:
                high = [c for c in plan.classifications
                        if TY.class_rank(c) >= TY.class_rank("personal")]
                if high:
                    self.bag.warn(
                        "CANON-W0006",
                        f"public endpoint {e.path} reaches "
                        f"{', '.join(high)} data", e.span,
                        facts={"path": e.path, "classifications": high,
                               "function": fi.qualname},
                        notes=["A publicly reachable endpoint that touches "
                               "protected data should be a deliberate "
                               "decision recorded in the change."])

            manifest.endpoints.append(plan)

        manifest.unused_resources = sorted(
            r.name for r in resources if r.name not in used_resources)
        for name in manifest.unused_resources:
            r = next(x for x in resources if x.name == name)
            self.bag.warn(
                "CANON-W0001",
                f"resource {name!r} is declared but nothing uses it", r.span,
                facts={"resource": name, "kind": r.kind},
                notes=["Unused infrastructure is cost and attack surface "
                       "that nothing is watching."])

        return manifest


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def parse_tract(source: str, filename: str = "<memory>"):
    """Parse Tract source. Returns (Canon Module, resources, Bag)."""
    lx = Lexer(source, filename)
    toks = lx.run()
    p = TractParser(toks, source, filename, lx.bag)
    mod = p.parse_module()
    mod.language = "tract"
    return mod, p.resources, p.bag


def plan(source: str, cr, resources=None, bag=None, module_name="") -> Manifest:
    """Plan a deployment from parsed resources and a checked program."""
    return Planner(bag or Bag()).plan(resources or [], cr, module_name)
