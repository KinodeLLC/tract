"""Tract: infrastructure derived from the program's capability footprint."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "canon" / "src"))
sys.path.insert(0, str(ROOT / "tract" / "src"))

from canon.checker import check  # noqa: E402
from canon.diagnostics import Bag  # noqa: E402
from canon.parser import parse  # noqa: E402
from tract import parse_tract, plan  # noqa: E402

PROGRAM = r'''
module orders

record Customer {
  id: Text
  email: Text
  classify email personal
}

record Order {
  id: Text
  customer: Customer
  total: Int
}

record Receipt {
  order_id: Text
}

effect store {
  write(key: Text, value: Text) -> Unit
  read(key: Text) -> Option<Text>
}

effect mail {
  send(to: Text, subject: Text, body: Text) -> Unit
}

fn persist(o: Order) -> Unit
  intent "Write an order to storage."
  uses store.write
{
  store.write(o.id, o.customer.id)
}

fn notify(o: Order) -> Unit
  intent "Email the customer."
  uses mail.send
{
  mail.send(o.customer.email, "Your order", o.id)
}

fn submit(o: Order) -> Receipt
  intent "Persist an order and confirm it."
  uses store.write, mail.send
  ensures result.order_id == o.id
{
  do persist(o)
  do notify(o)
  Receipt { order_id: o.id }
}

fn lookup(id: Text) -> Option<Text>
  intent "Read an order back."
  uses store.read
{
  store.read(id)
}
'''

INFRA = r'''
module orders.infra

resource api: HttpService {
  intent "The public order surface."
  expose orders.submit at "/orders" method "POST"
  expose orders.lookup at "/orders/lookup" method "GET"
  region "us-east-1"
  environment "production"
  scale_to 20
  budget money 500
  quota rps 1000
}

resource orders_table: Table {
  schema Order
  key id
  region "us-east-1"
  retention 2555 days
  budget money 120
}

resource postbox: Mailer {
  region "us-east-1"
  quota daily 50000
}
'''

# Removes the Mailer, so the notify path has nothing to provide mail.send.
MISSING_MAILER = INFRA.replace(
    'resource postbox: Mailer {\n  region "us-east-1"\n  quota daily 50000\n}\n',
    "")

# Declares a resource nothing reaches.
UNUSED = INFRA + '''
resource spare_cache: Cache {
  region "us-east-1"
}
'''

# Exposes something that is not a function.
BAD_EXPOSE = INFRA.replace('expose orders.lookup at "/orders/lookup" method "GET"',
                           'expose orders.lookupp at "/orders/lookup" method "GET"')

# A Table cannot host endpoints.
BAD_HOST = INFRA.replace("resource orders_table: Table {\n  schema Order",
                         'resource orders_table: Table {\n'
                         '  expose orders.submit at "/x" method "POST"\n'
                         "  schema Order")

PUBLIC_PII = INFRA.replace('expose orders.submit at "/orders" method "POST"',
                           'expose orders.submit at "/orders" method "POST" public')


def build(infra_src=INFRA):
    prog_mod, prog_bag = parse(PROGRAM, "orders.canon")
    infra_mod, resources, infra_bag = parse_tract(infra_src, "orders.tract")
    bag = Bag()
    bag.extend(prog_bag)
    bag.extend(infra_bag)
    if bag.has_errors:
        return None, None, bag
    cr = check([prog_mod, infra_mod], bag)
    if cr.bag.has_errors:
        return None, None, cr.bag
    manifest = plan(infra_src, cr, resources, cr.bag, "orders.infra")
    return cr, manifest, cr.bag


def main():
    failures = []

    def case(name, fn):
        try:
            print(f"  ok    {name}: {fn()}")
        except AssertionError as ae:
            failures.append(name)
            print(f"  FAIL  {name}: {ae}")

    cr, manifest, bag = build()
    if manifest is None:
        print(bag.render(INFRA))
        return 1
    errs = [d for d in bag if d.severity.value == "error"]
    if errs:
        for d in errs:
            print(d.render(INFRA))
        return 1

    print("derived manifest")

    def t_endpoints():
        paths = sorted(e.path for e in manifest.endpoints)
        assert paths == ["/orders", "/orders/lookup"], paths
        return f"{len(manifest.endpoints)} endpoints: {paths}"
    case("exposed functions become endpoints", t_endpoints)

    def t_capabilities_derived():
        submit = next(e for e in manifest.endpoints if e.path == "/orders")
        assert set(submit.capabilities) == {"store.write", "mail.send"}, \
            submit.capabilities
        # The endpoint never declares these; they come from the call graph.
        return (f"/orders needs {submit.capabilities}, computed from its "
                f"call graph")
    case("an endpoint's capabilities are computed, not declared",
         t_capabilities_derived)

    def t_satisfaction():
        submit = next(e for e in manifest.endpoints if e.path == "/orders")
        assert submit.satisfied_by["store.write"] == "orders_table", \
            submit.satisfied_by
        assert submit.satisfied_by["mail.send"] == "postbox", \
            submit.satisfied_by
        return f"each capability attributed to a resource: {submit.satisfied_by}"
    case("every capability is matched to the resource that provides it",
         t_satisfaction)

    def t_classifications():
        submit = next(e for e in manifest.endpoints if e.path == "/orders")
        assert "personal" in submit.classifications, submit.classifications
        return f"/orders reaches {submit.classifications} data"
    case("an endpoint's reachable data classifications are computed",
         t_classifications)

    def t_budget():
        assert manifest.total_money_budget == 620, manifest.total_money_budget
        return f"total declared budget {manifest.total_money_budget}"
    case("resource budgets are summed", t_budget)

    def t_render():
        text = manifest.render()
        assert "POST /orders -> orders.submit" in text, text
        assert "needs mail.send, store.write" in text, text
        return f"{len(text.splitlines())} line manifest"
    case("the manifest renders", t_render)

    print("\ncoverage checks")

    def t_missing_provider():
        _, m, b = build(MISSING_MAILER)
        assert b.has_errors, "a missing provider was not caught"
        d = next(x for x in b if x.code == "CANON-E0403")
        assert d.facts["capability"] == "mail.send", d.facts
        assert "Mailer" in d.facts["resource_kinds_that_provide_it"], d.facts
        return d.message
    case("exposing a function with no resource for its capability fails",
         t_missing_provider)

    def t_unused():
        _, m, b = build(UNUSED)
        assert m is not None, b.render(UNUSED)
        assert "spare_cache" in m.unused_resources, m.unused_resources
        w = next(x for x in b if "is declared but nothing uses it" in x.message)
        return w.message
    case("a resource nothing reaches is reported", t_unused)

    def t_bad_expose():
        _, m, b = build(BAD_EXPOSE)
        assert b.has_errors, "exposing a non-function was not caught"
        d = next(x for x in b if "not a function in this program" in x.message)
        return d.message
    case("exposing something that is not a function fails", t_bad_expose)

    def t_bad_host():
        _, m, b = build(BAD_HOST)
        assert b.has_errors, "a Table was allowed to host endpoints"
        d = next(x for x in b if "cannot expose endpoints" in x.message)
        return d.message
    case("only hosting resources may expose endpoints", t_bad_host)

    def t_public_pii():
        _, m, b = build(PUBLIC_PII)
        assert m is not None, b.render(PUBLIC_PII)
        w = next((x for x in b if "public endpoint" in x.message), None)
        assert w is not None, [x.message for x in b]
        return w.message
    case("a public endpoint reaching protected data is flagged", t_public_pii)

    print("\nRESULT:", "pass" if not failures else f"FAIL ({failures})")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
