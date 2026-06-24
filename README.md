# Advanced Interactive Digitizer

Interactive plot digitizer for extracting numerical data from graph images with axis calibration, manual correction, project saving, and symbol-assisted point detection.

This project is aimed at research workflows where extracted points must be revisable and auditable. The raw image coordinates are kept together with calibrated data coordinates so that digitized data can be checked later instead of becoming another mysterious CSV artifact.

## Current scope

The v0.1 goal is a reliable manual-first digitizer:

- Load plot images (`png`, `jpg`, `bmp`, `tif`)
- Calibrate X and Y axes from two clicked reference points each
- Support linear and base-10 logarithmic axes
- Create named data series
- Add points manually with optional template-based refinement
- Learn a plot marker from a legend bounding box
- Detect matching markers in bulk using OpenCV template matching
- Delete the latest point in the active series
- Export CSV with both data coordinates and raw image pixels
- Save/load digitizing sessions as `.aid.json`

Automatic detection is intentionally treated as an assistant to manual digitizing, not as magic. Magic is usually just bugs wearing nicer shoes.

## Installation

```bash
git clone https://github.com/GTT10/advanced-interactive-digitizer.git
cd advanced-interactive-digitizer
python -m pip install -e ".[dev]"
```

## Run the GUI

After installation:

```bash
aidigitizer
```

For quick local use without installing the console script:

```bash
python digitizer_gui.py
```

## Basic workflow

1. Click **画像を読み込む** and open a graph image.
2. Click **系列追加** and create a series label.
3. Click **X軸校正**.
   - Enter the two known X values.
   - Select `linear` or `log10`.
   - Click the two corresponding positions on the image.
4. Click **Y軸校正** and repeat the same process for the Y axis.
5. Click **点追加モード** and click data points.
6. Use **最後の点を削除** if a point is wrong.
7. Use **CSVエクスポート** to export extracted data.
8. Use **プロジェクトを保存** to save a revisable `.aid.json` session.

## CSV format

CSV exports include calibrated data coordinates and raw image coordinates:

```csv
label,data_x,data_y,image_x,image_y,note
AMN,0.5,50.0,320,240,
```

If the axes have not been calibrated, `data_x` and `data_y` are left blank while `image_x` and `image_y` are still exported.

## Project structure

```text
advanced-interactive-digitizer/
├─ src/aidigitizer/
│  ├─ calibration.py   # image pixel -> graph coordinate mapping
│  ├─ core.py          # OpenCV template learning and matching
│  ├─ gui.py           # PyQt6 user interface
│  ├─ models.py        # point, series, project dataclasses
│  └─ project.py       # JSON and CSV IO
├─ tests/
├─ digitizer_core.py   # backward-compatible wrapper
├─ digitizer_gui.py    # backward-compatible wrapper
└─ pyproject.toml
```

## Development

Run tests:

```bash
pytest
```

Run linting:

```bash
ruff check .
```

## Notes

This is not yet a full replacement for mature tools such as WebPlotDigitizer. The near-term priority is correctness and reproducibility for research use: axis calibration, clean state management, editable points, and stable exports. Fancy detection can come after the boring parts stop being wrong.
