```markdown
# QuantVista Development Patterns

> Auto-generated skill from repository analysis

## Overview
This skill teaches the core development patterns and conventions used in the QuantVista Python codebase. You'll learn how to structure files, write and commit code, and organize tests according to the project's established practices. This guide is ideal for new contributors or anyone seeking to align their work with QuantVista's standards.

## Coding Conventions

### File Naming
- Use **snake_case** for all Python files.
  - Example: `data_loader.py`, `model_utils.py`

### Import Style
- Both absolute and relative imports are used.
  - Example (absolute):
    ```python
    import numpy as np
    from quantvista.utils import calculate_metrics
    ```
  - Example (relative):
    ```python
    from .preprocessing import clean_data
    ```

### Export Style
- Default export style: Python modules and functions are exposed as-is, without explicit `__all__` unless necessary.

### Commit Messages
- Use **conventional commits** with the `feat` prefix for new features.
  - Example:
    ```
    feat: add time series forecasting module
    ```
- Keep commit messages concise (average ~74 characters).

## Workflows

### Feature Development
**Trigger:** When adding a new feature to the codebase  
**Command:** `/feature-dev`

1. Create a new branch for your feature.
2. Implement the feature following coding conventions.
3. Add or update tests as needed.
4. Commit changes using the `feat:` prefix.
5. Open a pull request for review.

### Testing
**Trigger:** When running or writing tests  
**Command:** `/run-tests`

1. Locate or create test files following the `*.test.*` pattern (e.g., `data_loader.test.py`).
2. Write tests for new or updated functionality.
3. Run tests using your preferred Python test runner (framework is not specified).
4. Ensure all tests pass before merging.

## Testing Patterns

- Test files are named with the pattern `*.test.*` (e.g., `module.test.py`).
- The specific testing framework is not enforced; use standard Python testing practices.
- Example test file:
  ```python
  # data_loader.test.py
  def test_load_data():
      result = load_data('test.csv')
      assert result is not None
  ```

## Commands
| Command        | Purpose                                |
|----------------|----------------------------------------|
| /feature-dev   | Start a new feature development workflow|
| /run-tests     | Run or write tests for the codebase    |
```
