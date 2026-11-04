# Changelog

Every release of the `privateterms` crate, newest first. release-plz writes each entry
from the Conventional Commits a release carries.

## [Unreleased]

## [0.1.2](https://github.com/nickderobertis/privateterms/compare/v0.1.1...v0.1.2) - 2026-11-04

### Performance

- *(matcher)* clear clean non-ASCII text without normalizing it ([#10](https://github.com/nickderobertis/privateterms/pull/10))

## [0.1.1](https://github.com/nickderobertis/privateterms/compare/v0.1.0...v0.1.1) - 2026-11-03

### Performance

- *(matcher)* scan text with no private term at little more than the cost of reading it ([#7](https://github.com/nickderobertis/privateterms/pull/7))

## [0.1.0](https://github.com/nickderobertis/privateterms/releases/tag/v0.1.0) - 2026-11-03

### Added

- publish the private-terms specification, its Rust SDK and its conformance suite ([#2](https://github.com/nickderobertis/privateterms/pull/2))
