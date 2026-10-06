# Test Coverage Report

Generated with:

```bash
python -m pytest --cov=. --cov-report=term-missing --cov-report=html
```

Requirement: **>80%**. Achieved: **97%** of statements and branches, across
**227 passing tests**.

The browsable HTML version is committed at [`../htmlcov/index.html`](../htmlcov/index.html)
— open that file in a browser for line-by-line highlighting. `coverage.xml` is
also committed for CI tools.

## Result

```
---------- coverage: platform win32, python 3.13.9-final-0 ----------

Name                    Stmts   Miss Branch BrPart  Cover   Missing
-------------------------------------------------------------------
config.py                 121      4     56      4    95%   139, 162, 178-179
data_loader.py             86      0     32      1    99%   167->169
main.py                   168      6     38      2    96%   283, 381, 443-446
models.py                  76      0     14      0   100%
observers.py               75      5     10      2    89%   75, 79->exit, 84-85, 92, 175
progress_store.py         137      1     40      3    98%   90->92, 108, 169->164
quiz_engine.py            185      5     28      2    97%   52, 56, 81, 151, 395->exit, 439
stats_reporter.py          87      0     24      0   100%
ui.py                      75      0     18      0   100%
utils/__init__.py           0      0      0      0   100%
utils/file_handler.py      74      6     12      2    91%   55, 57, 88-89, 160-161
-------------------------------------------------------------------
TOTAL                    1084     27    272     16    97%

227 passed
```

Branch coverage is on (`branch = true` in `pyproject.toml`), so these figures
count both statements and decision outcomes. `tests/` and `conftest.py` are
excluded from measurement — covering the test code with itself would inflate the
number without saying anything about the application.

## What the remaining 3% is

The uncovered lines are, deliberately, the ones that cannot be exercised without
a real terminal or a real filesystem failure:

| Location | Why it is uncovered |
| --- | --- |
| `ui._enable_windows_ansi` internals | Needs a genuine Windows console handle; marked `# pragma: no cover` |
| `quiz_engine` protocol method bodies | `...` stubs on `Protocol` classes, never executed |
| `utils/file_handler` permission branches | `os.access` denial and mid-write `OSError` need a filesystem the test process cannot create portably |
| `main` `__main__` guard and `sys.exit` path | Process-level entry, covered indirectly by `test_main_entry_point_exits_with_the_run_code` |
| `observers` logger fallbacks | Default-logger branches taken only when no logger is injected |

Nothing uncovered is business logic. Every grading rule, every validation rule,
every mode-ordering rule and every statistic is exercised by a test.

## Test distribution

| Module under test | Test file | Tests |
| --- | --- | --- |
| `config` | `tests/test_config.py` | 28 |
| `data_loader` | `tests/test_flashcard_loader.py` | 26 |
| `quiz_engine` | `tests/test_quiz_modes.py` | 26 |
| `main` | `tests/test_cli.py` | 26 |
| `models` | `tests/test_models.py` | 25 |
| `ui` | `tests/test_ui.py` | 25 |
| `progress_store` | `tests/test_progress_store.py` | 23 |
| `stats_reporter` | `tests/test_stats_reporter.py` | 21 |
| Session, observers, CLI end-to-end | `tests/test_integration.py` | 14 |
| `utils.file_handler` | `tests/test_file_handler.py` | 13 |
| **Total** | | **227** |

## Scenarios the project brief names

| Required test | Where |
| --- | --- |
| `test_load_valid_flashcards_array` | `tests/test_flashcard_loader.py` |
| `test_load_invalid_json` | `tests/test_flashcard_loader.py` |
| `test_load_missing_required_field` | `tests/test_flashcard_loader.py` |
| `test_quiz_mode_factory` | `tests/test_quiz_modes.py` |
| `test_adaptive_mode_behavior` | `tests/test_quiz_modes.py` |
| `test_full_session` | `tests/test_integration.py` |

## Other quality gates

```
python -m flake8 .                        0 errors
python -m mypy .                          0 errors across 23 source files
python -m bandit -c pyproject.toml -r .   0 issues (2 documented # nosec)
python -m black --check .                 all files formatted
python -m isort --check-only .            imports ordered
```
