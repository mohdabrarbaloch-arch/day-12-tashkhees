# Usage

## The workflow

1. **Sign in** — or create an account. Passwords need 8+ characters with at least one letter
   and one digit.
2. **Upload a study** — drag a chest radiograph onto the drop zone, or tap to choose. Add a
   patient reference and pick the view (PA / AP / lateral).
3. **Read the measurements** — the analysis runs automatically on upload. Each finding shows
   the measured value, its reference range, a flag, and a confidence.
4. **Check the segmentation** — switch the viewer to *Segmentation* to see which lung fields
   the engine actually measured.
5. **Generate a report** — one click composes technique, findings, and impression, with the
   mandatory disclaimer attached. Print it or read it on screen.

## Reading a finding

Each finding is a card with four pieces of information:

```
Cardiothoracic ratio                    0.52 ratio
[==============|=====]                  ← where the value sits in its range
ref 0.00–0.50 · HIGH · confidence 78%
The cardiac silhouette occupies more than half the thoracic width...
```

- **Value** — the measurement, in the units shown.
- **Bar** — the value's position within its reference range. A bar that runs past the end
  means the value is outside.
- **Flag** — `NORMAL`, `LOW`, or `HIGH`.
- **Confidence** — how much to trust this finding. It combines image quality with how far the
  value sits from the boundary. A value barely over the line on a noisy film gets low
  confidence; a value well past it on a clean film gets high confidence.

## What the confidence number means

Confidence is **not** a probability of disease. It is a statement about the measurement:

- For a **normal** finding, confidence reflects image quality — how sure we are that the
  measurement is genuinely in range.
- For an **abnormal** finding, confidence grows with distance from the boundary and shrinks
  with poor image quality.

A low-confidence abnormal finding on a poor film is the engine telling you it can't measure
this reliably — not that the patient is fine.

## Image requirements

| Requirement | Value |
|---|---|
| Formats | PNG, JPEG, WebP |
| Max size | 12 MB |
| Min dimensions | 256 × 256 px |
| Colour | any (converted to grayscale) |

The engine downscales anything larger than 1024 px on the long side before measuring, so
upload resolution doesn't change the result.

## Re-running an analysis

The *Re-run analysis* button runs the engine again and appends a new result. Every run is
kept, so you can compare. `GET /api/analysis/{id}/all` returns the full history.

## Deleting a study

*Delete* removes the study, all its analyses, all its reports, and the stored image file.
This cannot be undone.

## Limitations you should know about

- **It measures, it does not diagnose.** The engine reports the cardiothoracic ratio and lung
  field densities. It does not detect pneumonia, nodules, pneumothorax, or any specific
  pathology, because it is not a trained diagnostic model.
- **It expects a frontal chest film.** A lateral view, a CT slice, or a photo of a screen will
  produce meaningless numbers. The quality gate will usually flag them, but not always.
- **Reference ranges are population-level.** A CTR of 0.50 is a conventional threshold, not a
  personal one. Clinical context always wins.
- **Not for clinical use.** See the disclaimer in every report.
