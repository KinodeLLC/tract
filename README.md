# Tract

Infrastructure derived from the program that runs on it.

Part of the [Kinode](../kinode-stack) stack.

## Install

```sh
pip install -e .
```

## A deployment

```tract
module lending.platform

resource api: HttpService {
  intent "The origination surface used by the broker portal."
  expose lending.origination.originate at "/loans/originate" method "POST"
  region "eu-west-1"
  environment "production"
  scale_to 24
  quota rps 400
  budget money 900
}

resource loan_ledger: Table {
  schema LoanOffer
  key reference
  retention 2555 days
  budget money 300
}

resource credit_bureau: ExternalService {
  intent "The credit reference agency. Billed per pull and rate limited."
  provides bureau
  quota daily 20000
}

resource postbox: Mailer {
  quota daily 250000
}
```

## The difference from infrastructure-as-code

Ordinary IaC describes what to provision. Tract describes what to **expose**,
and derives what must be provisioned from the capability footprint of the code
behind it.

Exposing a function whose call graph writes to storage, with no storage
declared, is a compile error — not a deployment that succeeds and then fails at
the first request:

```
error[CANON-E0403]: lending.origination.originate needs 'ledger.append' but no
                    declared resource provides it
  capability: ledger.append
  resource_kinds_that_provide_it: ['Table']
  try: declare a resource that provides 'ledger'
  note: The capability comes from the function's call graph, not from a
        declaration, so this is what the endpoint will actually try to do.
```

An endpoint's stated permissions and its actual reach are the same number by
construction, because the permissions are computed.

## What it checks

- Every capability an exposed function can reach is provided by some declared
  resource
- Resources nothing reaches are reported — unused infrastructure is cost and
  attack surface nobody is watching
- A resource that provides nothing and hosts nothing is an error
- Only hosting kinds may expose endpoints
- A named schema exists and has the field being keyed on
- Dependencies between resources resolve
- A public endpoint reaching `personal` or more sensitive data is flagged

## The manifest

```
$ canon check examples/lending
deployment manifest for lending.platform
  resource api: HttpService, eu-west-1, scale 24, budget 900
  resource loan_ledger: Table, eu-west-1, budget 300
  resource credit_bureau: ExternalService, eu-west-1, budget 120
  POST /loans/originate -> lending.origination.originate
      needs bureau.pull, ledger.append, ledger.commit, ledger.reverse, notify.email
      touches personal, pseudonymous
```

Generated from the program, so a code change that widens what it touches
changes the manifest in the same commit.

## Resource kinds

| Kind | Provides |
| --- | --- |
| `HttpService` | hosts endpoints |
| `Table` | `store`, `db`, `table`, `ledger` |
| `Queue` | `queue`, `events`, `workflow` |
| `Cache` | `cache` |
| `ObjectStore` | `blobs`, `files`, `objects` |
| `Mailer` | `mail`, `mailer`, `notify` |
| `ModelAccess` | `model` |
| `Secret` | `secrets` |
| `Schedule` | `time`, `timer` |
| `WorkflowEngine` | `workflow` |
| `ExternalService` | whatever it declares |

Any resource may add `provides <effect>` for vocabularies Tract does not know.
`log`, `audit` and `random` are ambient and need no resource.

## Usage

```python
from tract import parse_tract, plan

mod, resources, bag = parse_tract(text, "platform.tract")
cr = check([program_mod, mod], bag)
manifest = plan("", cr, resources, cr.bag, "lending.platform")
print(manifest.render())
```

## Tests

```sh
python tests/smoke_tract.py
```

## Licence

Apache-2.0. Copyright Kinode.
