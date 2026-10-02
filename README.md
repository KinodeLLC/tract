# Tract

infrastructure that comes off the program instead of sitting next to it.

part of [kinode](https://github.com/KinodeLLC/kinode-stack).

## install

```sh
pip install -e .
```

## example

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

## coverage

normal infrastructure as code has you describe what to provision. here you say
what to expose and tract works out what has to exist from the effects the code
behind it can actually reach

if you expose a function whose call graph writes to storage and you have not
declared any storage you get a compile error, instead of a deploy that goes out
fine and then dies on the first request

```
error[CANON-E0403]: lending.origination.originate needs 'ledger.append' but no
                    declared resource provides it
  capability: ledger.append
  resource_kinds_that_provide_it: ['Table']
  try: declare a resource that provides 'ledger'
```

the permissions on an endpoint and what it can actually reach are the same
number because the permissions get computed, you do not write them

## checks

every capability an exposed function can reach has a resource providing it, and
resources nothing reaches get flagged since that is cost and attack surface with
nobody watching it. a resource that provides nothing and hosts nothing is an
error. only hosting kinds can expose endpoints. a schema you name has to exist
and have the field you are keying on. dependencies between resources have to
resolve. a public endpoint that reaches `personal` or worse gets flagged

## manifest

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

generated off the program, so a code change that widens what it touches shows up
in the manifest in the same commit as the code

## resource kinds

| kind | provides |
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

any resource can add `provides <effect>` for effect names tract does not know
about. `log`, `audit` and `random` are ambient so they do not need a resource

## usage

```python
from tract import parse_tract, plan

mod, resources, bag = parse_tract(text, "platform.tract")
cr = check([program_mod, mod], bag)
manifest = plan("", cr, resources, cr.bag, "lending.platform")
print(manifest.render())
```

## tests

```sh
python tests/smoke_tract.py
```

## licence

Apache-2.0, Kinode.
