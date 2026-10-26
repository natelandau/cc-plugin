---
name: tufte-viz
description: |
    Ideate and critique data visualizations using Edward Tufte's principles from "The Visual Display of Quantitative Information." Use this skill when:
    (1) Designing new data visualizations or charts
    (2) Critiquing or improving existing visualizations
    (3) Reviewing dashboards or reports for graphical integrity
    (4) Deciding between visualization approaches
    (5) Reducing chartjunk or improving data-ink ratio
    (6) Planning small multiples or high-density displays
    Applies principles: data-ink ratio, chartjunk elimination, graphical integrity, lie factor, small multiples, and data density.
---

# Tufte Visualization Ideation

Apply Edward Tufte's principles to design clear, honest, high-density data
visualizations.

## Workflow for a new visualization

1. Clarify the data story. Which comparisons matter? What is the key insight?
   Who is the audience?

2. Select the approach:
   - A strong comparison need calls for small multiples.
   - Dense data calls for a data table or sparklines.
   - A time series calls for a line chart with a minimal grid.
   - A part-to-whole relation calls for a bar chart or a table, not a pie
     chart.

3. Design with data-ink in mind. Start minimal and add only what is
   necessary. Every element must earn its ink. Default to grayscale, and use
   color with purpose.

4. Apply the eraser test. For every element (label, tick, gridline, border,
   annotation), ask whether it can be erased without losing information that
   nothing else conveys. Watch for duplicate encodings: a numeric label next to
   a value a tick already marks, a legend that duplicates direct labels, a
   per-panel scale annotation that duplicates a shared-scale caption. When two
   elements compete for the same job, keep one.

5. Apply the collision test. For every text element in the plot (axis labels,
   point annotations, epoch labels, baseline labels, notes), draw its bounding
   box in your mind. Does another text element, a data line, or a cluster of
   dense markers cross that box? The eraser test catches redundant elements.
   The collision test catches crowded ones. Both must pass. Standard fixes:
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

- `references/tufte-principles.md`: the core principles from The Visual
  Display of Quantitative Information: lie factor, data-ink, chartjunk, small
  multiples, integrity.
- `references/analytical-design.md`: the extensions from Envisioning
  Information, Visual Explanations, and Beautiful Evidence: the six principles
  of analytical design, sparklines, layering and separation, micro and macro
  readings, range-frames, causality, confections. Load it when designing
  dashboards, dense displays, sparklines, or explanatory graphics.

## Quick checklist

- [ ] The lie factor is close to 1.0, with no visual distortion.
- [ ] The data-ink ratio is as high as the data allows.
- [ ] There is no chartjunk.
- [ ] The labels are clear.
- [ ] The chart answers "compared to what?".
- [ ] The chart shows causality or mechanism where relevant.
- [ ] The chart is multivariate, not over-reduced.
- [ ] Words, numbers, and images are integrated, not segregated.
- [ ] The chart reveals several levels of detail, micro and macro.
- [ ] The primary data dominates and the secondary data recedes.
- [ ] The data density suits the display.
