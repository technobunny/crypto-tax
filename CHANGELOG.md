# Changelog

## v1.0.3 - 2022-04-11

### Added
- Added price splitting and merging functionality in examples/
- Added support for fees in a currency not present in the trade itself (e.g. when the exchange charges you with their own coin)

### Changed
- Changed to Python 3.9 (most visible w.r.t. no more imports of List/Dict/Tuple from typing)
- Streamlined price lookup
- Streamlined execution normalization
- Refactored common code and moved some code into more appropriate modules

## v1.0.2 - 2022-04-01

### Added
- Transfer support to update quantities between matches

### Changed
- Refactored match.py so it gets only executions coming in
- Changed method names to indicate 'private'

## v1.0.1 - 2022-03-28

### Added
- Ability to specify quantity of B in A/B pair per trade

### Changed
- README to reflect new trade CSV format, clean up text, and update roadmap
- The format of this changelog

### Fixed
- Fee handling bugs and unnecessary calls to historic price lookup for output currency

## v1.0.0 - 2022-03-28

### Added
- Added this changelog

### Changed
- Updated the README
