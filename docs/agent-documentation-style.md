# Agent Documentation Style Guide

## Purpose

This guide defines the documentation style for agent code in this project. Follow Simplified Technical English (STE) rules. Keep documentation simple and direct.

## Principles

### Use Simple Words

| Do Not Use | Use |
|------------|-----|
| utilize | use |
| implement | make |
| facilitate | help |
| execute | run |
| initialize | start |
| terminate | stop |
| approximately | about |
| demonstrate | show |

### Use Active Voice

- **Good**: The function extracts fields.
- **Bad**: Fields are extracted by the function.

### Use Present Tense

- **Good**: Returns the comparison result.
- **Bad**: Will return the comparison result.

### One Sentence Per Line

Write each sentence on its own line. This makes diffs clear.

## Function Documentation

### Format

```python
def function_name(param: type) -> return_type:
    """Short description of what the function does.

    Args:
        param: Description of parameter.

    Returns:
        Description of return value.
    """
```

### Rules

1. **One-line summary** — First line describes what the function does.
2. **No empty lines** — Keep docstring compact.
3. **Args and Returns only** — Omit Raises, Yields, Examples unless needed.
4. **Type hints in code** — Do not repeat types in docstring.

### Example

```python
def compare_fields(si_value: str, bl_value: str) -> bool:
    """Compare SI value against BL value.

    Args:
        si_value: Source of truth value from Shipping Instruction.
        bl_value: Value from Bill of Lading.

    Returns:
        True if values match after normalization.
    """
```

## Class Documentation

### Format

```python
class ClassName:
    """Short description of class responsibility.

    Attributes:
        attr_name: Description of attribute.
    """
```

### Rules

1. **One-line summary** — What the class does.
2. **List public attributes** — Only those users need to know.
3. **No method list** — Methods document themselves.

## Module Documentation

### Format

```python
"""Module description.

This module provides X functionality for Y.
"""
```

### Rules

1. **One-line summary** — First line tells what the module does.
2. **One paragraph max** — No multi-paragraph descriptions.

## Comments

### Inline Comments

- Put on same line as code when short.
- Start with `# ` (space after hash).
- Explain why, not what.

```python
threshold = 0.85  # High confidence required for auto-approval
```

### Block Comments

Avoid. Use function docstrings instead.

## Naming

- Functions: `verb_noun` — `extract_fields`, `normalize_weight`
- Classes: `Noun` — `EmailClassifier`, `FieldComparator`
- Constants: `UPPER_SNAKE` — `MAX_RETRIES`, `REQUIRED_FIELDS`
- Variables: `snake_case` — `email_id`, `comparison_result`

## What to Avoid

- Multi-line descriptions when one line works
- Redundant words ("This function returns..." → "Returns...")
- Future tense ("will return" → "returns")
- Passive voice ("is compared" → "compares")
- Latin abbreviations (e.g., i.e., e.g.) — use "that is" or "for example"
- Jargon without definition

## Quick Reference

| Element | Style |
|---------|-------|
| Function docstring | 3-5 lines max |
| Class docstring | 2-4 lines max |
| Module docstring | 1-2 lines max |
| Inline comment | Same line, explain why |
| Sentence length | Under 20 words |
| Paragraphs | None in docstrings |