# Testing the UTEC Layer Tools Plugin

This directory contains the automated test suite for the UTEC Layer Tools
QGIS plugin. Tests are powered by
[**pytest-qgis**](https://github.com/osgeosuomi/pytest-qgis), which boots
a real `QgsApplication` before running any tests — no QGIS GUI required.

---

## Directory Layout

```
tests/
├── conftest.py          # Shared fixtures (PluginContext init, helpers)
├── unit/                # Pure-Python tests — no QGIS needed
│   └── test_rename_utils.py
└── qgis/                # QGIS integration tests (real QgsApplication)
    ├── test_geopackage.py
    ├── test_general.py
    └── test_rename.py
```

---

## One-Time Setup (Windows · OSGeo4W)

> **Prerequisites**: QGIS ≥ 3.34 installed via OSGeo4W (the default for
> QGIS LTR on Windows). Your installation is at `C:\OSGeo4W`.

Open the **OSGeo4W Shell** (find it in the Start menu) and run:

```bat
:: Navigate to the project root
cd "C:\Users\fl\Documents\Python\QGIS-Plugin_Layer_Tools"

:: Create a venv that inherits QGIS's Python packages
C:\OSGeo4W\apps\Python312\python.exe -m venv .venv --system-site-packages

:: Activate the venv
.venv\Scripts\activate

:: Install test dependencies
pip install pytest pytest-qgis pytest-qt pytest-cov
```

> **Why `--system-site-packages`?**  QGIS ships its own Python installation
> at `C:\OSGeo4W\apps\Python312`. This flag lets your venv "see through" to
> those packages (`qgis`, `osgeo`, `PyQt5`/`PyQt6`, etc.) without copying
> them.

---

## Running Tests

Always activate the venv first (in the OSGeo4W Shell):

```bat
.venv\Scripts\activate
```

| Command | What it runs |
|---|---|
| `python -m pytest tests/unit/ -v` | Unit tests only — fast, no QGIS |
| `python -m pytest tests/qgis/ -v` | QGIS integration tests (headless) |
| `python -m pytest -v` | All tests (headless by default via `pyproject.toml`) |
| `python -m pytest -v --co` | List all collected tests without running them |
| `python -m pytest -v --cov=modules --cov-report=term-missing` | All tests + coverage report |

> The flag `--qgis-disable-gui` is set globally in `pyproject.toml`
> (`addopts`), so tests run headless by default. To visually debug a specific
> test (e.g., inspect the map canvas), pass `--qgis-enable-gui` on the
> command line to override it.

---

## VS Code Integration (optional)

Add this to your `.vscode/settings.json` to make VS Code's test runner work
with the OSGeo4W venv:

```json
{
    "python.defaultInterpreterPath": "${workspaceFolder}/.venv/Scripts/python.exe",
    "python.testing.pytestEnabled": true,
    "python.testing.pytestArgs": ["tests"]
}
```

> The VS Code test runner **must** be launched from an OSGeo4W-aware terminal
> (or from the OSGeo4W Shell) for the QGIS libraries to be found. The simplest
> approach is to open your project folder from within the OSGeo4W Shell using
> `code .`.

---

## Writing New Tests

### Unit test (no QGIS)

Add your file under `tests/unit/`. Import from `modules.*` directly — the
`conftest.py` session fixture has already initialised `PluginContext`.

### QGIS integration test

Add your file under `tests/qgis/`. Use any of these
[pytest-qgis fixtures](https://github.com/osgeosuomi/pytest-qgis#fixtures)
in your test signature:

| Fixture | Provides |
|---|---|
| `qgis_iface` | Stubbed `QgisInterface` |
| `qgis_new_project` | Clean `QgsProject` (layers wiped per test) |
| `qgis_processing` | Initialised processing framework |
| `qgis_bot` | GUI helper utilities |

Shared fixtures (`tmp_gpkg`, `memory_point_layer`, `clean_project`, …) are
defined in `tests/conftest.py`.

### Naming convention

Layer fixture names containing `layer`, `lyr`, `raster`, or `rast` are
automatically cleaned up by pytest-qgis to prevent segmentation faults.
Follow this convention when writing your own layer fixtures.
