# Changelog

keep a changelog format, semver. before 1.0 a breaking change bumps the minor.

## [Unreleased]

## [0.1.0] - 2026-09-21

### Added
- resources with regions, scaling, quotas, retention, budgets, dependencies
- endpoint capabilities computed off the call graph
- exposing a function no resource can cover is a compile error
- unused resources and public endpoints touching protected data get reported
- eleven resource kinds plus a `provides` clause
