# Repair ordered configuration merges with explicit-value semantics

This method was saved by the real model during task A and delivered to task B.

When to use: Independent services with a lowest-to-highest layer contract, explicit falsy values, whole-list replacement, and detached JSON-like results.

Not for:
- Contracts requiring list concatenation, deletion markers or highest-to-lowest input ordering.
- Claiming support for cyclic data or custom object copy semantics without extra tests.

## Method / 方法
Read the local contract and implementation and run the existing tests before editing. Distinguish absent keys from explicit falsy values: iterate every patch item without a truthiness filter. Process layers in declared lowest-to-highest order. Recurse only when both existing and incoming values are dictionaries; otherwise assign a deep copy of the incoming value, including lists, null, false, zero, and empty strings. Preserve the public signature. Add targeted tests for root/nested falsy overrides and newly introduced falsy keys, dictionary empty-patch versus cross-type empty-dictionary replacement, type changes in both directions, and dictionary-to-scalar-to-dictionary sequences that must not resurrect discarded keys. Test nested result mutation isolation for retained and replaced values, including dictionaries inside lists, and independent resolutions. Run the full local test suite and report observed coverage and unsupported input categories.

## Reuse checks / 复用验证
- A later false, zero, empty string, null or empty list wins at root and nested keys.
- An empty dictionary preserves existing dictionary keys but replaces an earlier non-dictionary.
- A dictionary replaced by a scalar must not reappear when a later dictionary arrives.
- Mutating nested dictionaries inside result lists must not change any input layer.
