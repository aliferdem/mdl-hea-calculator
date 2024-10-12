hea_phase_predictor/
├── __init__.py
├── main.py
├── ui/
│   ├── __init__.py
│   ├── main_window.py          # Main window class (MDLHEAPP)
│   ├── about_dialog.py         # Dialog class for the about section
│   ├── settings.py             # Settings management (Settings class)
│   ├── periodic_table.py       # UI elements and methods related to periodic table
├── workers/
│   ├── __init__.py
│   ├── alloy_calculation.py    # AlloyCalculationWorker class
│   ├── composition_generation.py  # CompositionGenerationWorker class
│   ├── excel_writer.py         # ExcelWriterWorker class
├── engine/
│   ├── __init__.py
│   ├── engine.py               # Engine class
├── utils/
│   ├── __init__.py
│   ├── io_helpers.py           # File reading/writing utilities
│   ├── ui_helpers.py           # Common UI methods like validated_line_edit
├── ui/
│   ├── styles/
│   │   ├── styleSheet_dark.qss
│   │   ├── styleSheet_light.qss
│   ├── icons/
│   ├── logo_dark.svg
├── LICENSE
├── README.md