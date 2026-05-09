---
name: inline-comments
description: "Use when adding, editing, or reviewing inline comments in any source file. Covers when to comment (WHY not WHAT) and rules for noqa and type-ignore comments."
---

## How to write inline comments

- Only comment to explain _why_, not _what_, assume the reader knows the language
- Never change or remove `noqa` or `type: ignore` comments unless the user explicitly asks you to do so or they are incorrect
- Remove any "what" comments unless they are explicitly asked for by the user

### Examples of good inline comment usage

Explain WHY certain steps are made:

```python
# Process items in reverse to ensure the most recent data is prioritized over older data to match user expectations
for items in reversed(items):
    item.price = 20  # Set the price to 20 to match the competitor's pricing strategy
```

Name non-obvious algorithms and clarify tricky expressions:

```python
# This loop uses the Fisher-Yates algorithm to shuffle the array
for i in range(len(arr) - 1, 0, -1):
    j = random.randint(0, i)
    arr[i], arr[j] = arr[j], arr[i]

if i & (i - 1) == 0:  # True if i is 0 or a power of 2
```
