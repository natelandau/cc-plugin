---
name: tufte-viz
description: >-
    Use when designing, critiquing, or choosing a data visualization, chart, or dashboard
    with Edward Tufte's principles: graphical integrity, lie factor, data-ink ratio,
    chartjunk, small multiples, data density.
disable-model-invocation: true
---

# Tufte Visualization Ideation

## Workflow for a new visualization

1. Clarify the data story: the comparisons that matter, the key insight, the audience.

2. Select the approach:
   - A strong comparison need calls for small multiples.
   - Dense data calls for a data table or sparklines.
   - A time series calls for a line chart with a minimal grid.
   - A part-to-whole relation calls for a bar chart or a table, not a pie
     chart.

3. Design for data-ink. Start minimal; add an element only when it earns its ink.
   Default to grayscale; use color only with a purpose.

4. Apply the eraser test. For every element (label, tick, gridline, border,
   annotation), ask whether it can be erased without losing information that
   nothing else conveys. Watch for duplicate encodings: a numeric label next to
   a value a tick already marks, a legend that duplicates direct labels, a
   per-panel scale annotation that duplicates a shared-scale caption. When two
   elements compete for the same job, keep one.

5. Apply the collision test. For every text element in the plot (axis labels,
   point annotations, epoch labels, baseline labels, notes), picture its bounding
   box. It fails if another text element, a data line, or a cluster of dense markers
   crosses that box. Both the eraser and collision tests must pass. Standard fixes:
   move explanatory prose out of the plot into the figcaption, relocate band
   or epoch labels to a strip above the plot, push baseline labels to the
   outside margin, and give each in-plot annotation a leader line. Watch
   especially for inverted axes (extreme values and annotations both want the
   top), shared-scale small multiples (labels stacked near zero in every
   panel), and dense scatter plots (text vanishes into the dot cloud).

6. Apply the Tufte test in `references/tufte-principles.md`.

## Workflow for a critique

1. Check graphical integrity. Calculate the lie factor if the proportions look
   off. Confirm the baselines and scales. Look for 3D distortion.
2. Identify chartjunk: decorative elements, heavy grids, 3D effects, moire
   patterns.
3. Evaluate the data-ink ratio. What can be erased? What is redundant?
4. Suggest improvements as specific before-and-after recommendations.

## References

- `references/tufte-principles.md`: core principles (lie factor, data-ink,
  chartjunk, small multiples, integrity) and the Tufte test.
- `references/analytical-design.md`: the six principles of analytical design,
  sparklines, layering and separation, micro and macro readings, range-frames,
  causality, confections. Read it when designing dashboards, dense displays,
  sparklines, or explanatory graphics.

## Quick checklist

- Lie factor close to 1.0, no visual distortion.
- Data-ink ratio as high as the data allows.
- No chartjunk.
- Clear labels.
- Answers "compared to what?".
- Shows causality or mechanism where relevant.
- Multivariate, not over-reduced.
- Words, numbers, and images integrated, not segregated.
- Several levels of detail, micro and macro.
- Primary data dominates; secondary data recedes.
- Data density suits the display.
