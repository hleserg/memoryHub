# Web Dashboard

A browser-based dashboard for the Atman project, built with Streamlit.

## Overview

The Web Dashboard provides a convenient browser interface for daily work with the Atman project, offering the same functionality as the TUI dashboard but in a modern web UI.

## Features

### 🎯 Features Tab
- View registered features (Factual Memory, Experience Store)
- Run feature demos (paced/fast mode)
- Browse feature documentation (English/Russian)
- Install dev dependencies

### 🧪 Tests Tab
- Run full test suite or specific test subsets
- Configure test options (verbose, coverage, parallel, fail-fast)
- View test results with pass/fail summary
- Browse test coverage reports
- Filter output (all tests / errors only)

### 📚 Docs Tab
- Navigate project documentation by section:
  - Architecture
  - Development
  - Features
  - Ideas
  - Research
- Browse markdown files with live preview
- Quick links to key documents (README, MANIFEST, SYSTEM)
- Language switching for bilingual docs (EN/RU)

## Installation

The web dashboard requires Streamlit, which is included in the project dependencies:

```bash
# Using uv (recommended)
uv pip install -e ".[dev]"

# Or using pip
pip install -e ".[dev]"
```

## Usage

### Running the Web Dashboard

There are several ways to start the web dashboard:

**1. Using the make command (recommended):**
```bash
make webui
```

**2. Using the entry point script:**
```bash
atman-web
# or
webui
```

**3. Using Streamlit directly:**
```bash
streamlit run src/atman/web_dashboard/app.py
```

The dashboard will open in your default browser at `http://localhost:8501`.

## Architecture

### Project Structure

```
src/atman/web_dashboard/
├── __init__.py           # Entry point with main() function
├── app.py                # Main Streamlit application (home page)
├── pages/
│   ├── 1_Features.py     # Features management page
│   ├── 2_Tests.py        # Test runner page
│   └── 3_Docs.py         # Documentation browser page
└── utils/
    ├── __init__.py       # Utilities package
    ├── cmd.py            # Command building (pytest, python, demo)
    └── runner.py         # Process execution utilities
```

### Key Components

#### 1. Main Application (`app.py`)
- Repository info display
- Quick navigation to main sections
- Custom CSS styling

#### 2. Features Page
- Feature selection from registry
- Demo execution (paced/fast modes)
- README viewer with language toggle
- Dev dependencies installer

#### 3. Tests Page
- Test suite configuration
- Real-time test execution
- Results parsing and display
- Coverage reporting

#### 4. Docs Page
- Hierarchical document navigation
- Markdown rendering
- Bilingual document support
- Quick access to key documents

#### 5. Utilities
- **`cmd.py`**: Command builders for pytest, Python scripts, and demos
- **`runner.py`**: Async/sync process execution with output streaming

## Design Philosophy

### Alignment with TUI Dashboard

The web dashboard mirrors the TUI dashboard's structure and functionality:

- **Same navigation**: Three main tabs (Features, Tests, Docs)
- **Same capabilities**: Run demos, execute tests, browse documentation
- **Same data sources**: Uses `atman.tui.features_registry` and `atman.tui.repo_root`

### Simplicity First

- **No authentication**: Internal tool, no security overhead
- **No database**: Stateless by design
- **No external services**: Self-contained, runs from repository

### User Experience

- **Responsive layout**: Adapts to different screen sizes
- **Real-time feedback**: Live output from running commands
- **Clear status**: Success/error indicators with exit codes
- **Minimal clicks**: Quick actions and navigation

## Differences from TUI Dashboard

| Aspect | TUI Dashboard | Web Dashboard |
|--------|--------------|---------------|
| **Interface** | Terminal-based (Textual) | Browser-based (Streamlit) |
| **Navigation** | Keyboard shortcuts | Mouse/touch friendly |
| **Output** | Rich console formatting | HTML/Markdown rendering |
| **Concurrency** | Async workers | Streamlit session state |
| **Deployment** | Runs in terminal | HTTP server (localhost) |

## Customization

### Adding New Pages

To add a new page to the dashboard:

1. Create a new file in `src/atman/web_dashboard/pages/` with prefix `N_PageName.py` (where N is the order number)
2. Configure page settings at the top:
   ```python
   import streamlit as st
   
   st.set_page_config(
       page_title="My Page - Atman Dashboard",
       page_icon="🔧",
       layout="wide"
   )
   ```
3. Implement your page content
4. The page will automatically appear in the sidebar

### Styling

Custom CSS can be added in the main `app.py` or individual pages using:

```python
st.markdown("""
    <style>
    .custom-class {
        /* your styles */
    }
    </style>
""", unsafe_allow_html=True)
```

## Testing

The web dashboard is excluded from code coverage (see `pyproject.toml`). Manual testing is recommended:

1. Start the dashboard: `make webui`
2. Test each page:
   - Features: Run a demo, view README
   - Tests: Execute test suite, check output
   - Docs: Navigate sections, view markdown files
3. Verify error handling (e.g., run tests that fail)

## Troubleshooting

### Dashboard Won't Start

**Problem**: `streamlit: command not found`

**Solution**: Install dependencies:
```bash
uv pip install -e ".[dev]"
```

### Repository Not Found

**Problem**: Error message "Repository root not found"

**Solution**: Run from within the Atman repository directory.

### Demo/Test Commands Fail

**Problem**: Commands exit with non-zero code

**Solution**: Check that dev dependencies are installed and repository is in valid state.

## Future Enhancements

Potential improvements for future versions:

1. **Real-time streaming**: Stream demo/test output as it happens (requires async Streamlit)
2. **Configuration persistence**: Save user preferences (layout, defaults)
3. **Multi-project support**: Manage multiple Atman instances
4. **Advanced analytics**: Test trend graphs, failure rate charts
5. **Integration with CI/CD**: Display build status, trigger pipelines

## Related Documentation

- [TUI Dashboard (Textual)](../../development/work-packages/README.md)
- [Features Registry](../../../src/atman/tui/features_registry.py)
- [Development Standard](../../development/DEVELOPMENT_STANDARD.md)

## References

- [Streamlit Documentation](https://docs.streamlit.io/)
- [Streamlit Gallery](https://streamlit.io/gallery)
- [Dashboard Research](../../research/dashboard-research.md)
