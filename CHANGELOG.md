# Changelog

Keep a Changelog format, SemVer. Pre-1.0: breaking changes bump the minor.

## [Unreleased]

## [0.1.0] - 2026-09-21

### Added
- Resources declared by kind, with regions, scaling, quotas, retention,
  budgets and dependencies.
- Endpoint capabilities computed from the call graph rather than declared.
- Coverage checking: exposing a function whose capabilities no resource
  provides is a compile error naming the capability and the kinds that would
  satisfy it.
- Reporting for unused resources and for public endpoints reaching protected
  data.
- Eleven resource kinds, plus a `provides` clause for effect vocabularies Tract
  does not know.
