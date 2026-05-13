## Data Visualization — Line Chart: How to use

This document explains the Line Chart controls available in the Data Visualization dialog and how to use them to make clear, informative trend charts.

### Where to find it
- Open the application and run a query or load a table so `Results` has data.
- Menu: Data Visualization → choose `Line Chart` in the `Chart Type` selector.

---

### Controls (what they do)

- Smoothing (line): integer rolling-window used to compute a moving average. Set to 0 or 1 to disable smoothing. A value of 3–7 is common for modest smoothing.

- Line width: controls the plotted line thickness. Default ~1.5. Use larger values (2.5–4) to emphasize the line.

- Color: choose a preset color for the line (Default lets Matplotlib pick a color from the palette).

- Show markers: when checked, markers are drawn at each data point.
- Marker type: pick circle, square, triangle, diamond, plus, or None. Choose None for dense series.
- Marker size: integer size of the marker in points.

- Emphasize X: enter the exact X-axis label (string) to visually emphasize that X value. The first matching point(s) will be highlighted with a large gold marker.

- Add trendline: add a computed trend overlay.
  - Trend type: Linear — fits a linear regression to the series (useful for directional trends).
  - Trend type: Moving Average — plots an additional rolling-mean series (uses the Smoothing window if set, otherwise uses 3).

- Show target: enables a horizontal target line. Enter a numeric value in the `target` input to draw a dashed red target line.

---

### Step-by-step examples

Example A — Clear trend with markers:
1. Select `Line Chart`.
2. Choose X and Y columns.
3. Set Line width = 2.5, Color = `Blue`.
4. Check `Show markers`, Marker type = `Circle (o)`, Size = 6.
5. Generate Chart.

Result: a thicker blue line with circular markers that clearly shows exact observations.

Example B — Smooth noisy data and show trend:
1. Select `Line Chart`.
2. Set Smoothing = 7.
3. Check `Add trendline` and choose `Moving Average`.
4. Optionally set Line width = 1.8 and uncheck markers for a cleaner look.
5. Generate Chart.

Result: the raw series is plotted and a dashed smoothed/trend line is overlaid, reducing volatility and revealing long-term direction.

Example C — Emphasize a peak and add a target:
1. Select `Line Chart`.
2. Enter the X label of the peak into `Emphasize X` (must match how X labels appear on the axis).
3. Check `Show target` and enter the numeric target value (e.g., 1000).
4. Generate Chart.

Result: the peak point(s) will be highlighted and a dashed red target line will be drawn across the chart.

---

### Implementation notes (for maintainers)
- Emphasize `Emphasize X`: the code matches string equality against the x-axis labels. If the X column is a datetime, the label text used on the axis must be matched (formatting matters).
- Trendline: Linear trends use numpy.polyfit on index positions (0..N-1) and plot the fitted values; Moving Average uses a rolling mean (pandas). If `numpy` isn't installed, the trendline will be skipped (no crash).
- Markers: when `Show markers` is unchecked, marker is set to None; otherwise a marker symbol is chosen from a small map.

---

### Tips & best practices
- For dense series (many points), avoid markers and use smoothing or moving-average trendlines to reveal the signal.
- Choose a slightly heavier line width (1.8–2.5) when using dark backgrounds so the line stands out.
- Use the target line sparingly — it's most effective when it's a meaningful benchmark (target, SLA, average).

---

### Troubleshooting
- If the emphasized point doesn't appear, verify the `Emphasize X` text exactly matches an X label (case-sensitive string match).
- If the trendline does not appear and you expect a linear fit, ensure `numpy` is available in your Python environment. The program will continue without failing if `numpy` is missing.
- If markers or colors look off, try toggling `Show markers` and regenerating the chart; some backends may render markers differently for very small sizes.

---

If you want, I can also add a small screenshot example and copyable snippets for generating equivalent charts using Matplotlib directly (useful for reproducible reports).
