# Flashcard Quizzer

A command-line flashcard trainer for memorising the things a new hire has to
know cold: server acronyms, HTTP status codes, language keywords. It loads a
deck from JSON, quizzes you in one of four modes, remembers what you keep
getting wrong, and reports back when you are done.

Built for the Udacity *AI-Assisted Software Development* project (cd14602) on
top of the provided starter skeleton.

```
$ python main.py -f data/glossary.json -m adaptive

Flashcard Quizzer - Glossary
Mode: adaptive   Cards: 10
Type your answer, "skip" to pass, or "exit" to stop early.
--------------------------------------------------------

Question 1
CDN
Your answer: content delivery network
Correct

Question 2
TLS
Your answer: transport security
Incorrect
  Answer: Transport Layer Security
```

## Requirements

- Python 3.10 or newer (developed and tested on 3.13)
- `pip`

The application itself imports **only the Python standard library**. Everything
in `requirements.txt` is a development tool: test runner, formatter, linters.
You can run the quiz on a machine with nothing installed but Python.

## Install

```bash
git clone <your-fork-url> flashcard-quizzer
cd flashcard-quizzer

# macOS / Linux
python3 -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate

python -m pip install -r requirements.txt
```

To just play the quiz, you can skip the install entirely:

```bash
python main.py -f data/glossary.json
```

## Usage

```bash
python main.py --help
python main.py -f data/glossary.json -m sequential
python main.py -f data/python_basics.json -m adaptive
python main.py -f data/http_status_codes.json -m random --seed 42
```

### Flags

| Flag | Meaning |
| --- | --- |
| `-f`, `--file PATH` | Deck to quiz on. Default `data/glossary.json`. |
| `-m`, `--mode MODE` | `sequential`, `random`, `adaptive` or `spaced`. |
| `-n`, `--limit N` | Stop after N questions. |
| `--seed N` | Seed the shuffle so a run can be reproduced exactly. |
| `--stats` | Show your saved progress for this deck, then exit. |
| `--validate` | Check the deck file is well-formed, then exit. |
| `--list-modes` | List the quiz modes and what each one does. |
| `--export {json,csv,md}` | Write a session report when the quiz ends. |
| `--export-path PATH` | Export to an exact file instead of a timestamped name. |
| `--config PATH` | Read settings from this file. |
| `--progress-file PATH` | Where cross-session history is kept. |
| `--no-progress` | Do not read or write the progress file. |
| `--no-color` | Plain text output. |
| `--no-timer` | Do not time answers or report timings. |
| `--hide-answers` | Do not reveal the answer after a wrong response. |
| `--log-level LEVEL` | `DEBUG` … `CRITICAL`. Default `WARNING`. |
| `--log-file PATH` | Log to a file instead of standard error. |
| `--version` | Print the version. |

### During a quiz

- Type the answer and press Enter. Grading ignores case, extra spaces and
  Unicode accent forms, so `  secure   SHELL ` matches `Secure Shell`.
- Type `skip`, `pass` or `?` to give up on a card. It counts as incorrect.
- Type `exit` or `quit`, or press **Ctrl+C** or **Ctrl+D**, to stop early. You
  still get the summary for the questions you answered.

## Quiz modes

| Mode | Behaviour |
| --- | --- |
| `sequential` | Asks the cards in deck order, each once. |
| `random` | Shuffles the deck and asks each card once. Use `--seed` to repeat a run. |
| `adaptive` | Puts the cards you have missed before at the front, and re-asks a card you miss during the session. |
| `spaced` | Reviews by schedule: the most overdue cards first, using an SM-2 style interval stored per card. |

`adaptive` and `spaced` read the progress file, so they get better the more you
use them. With `--no-progress` they fall back to neutral scores and still work.

## Deck format

A deck is a JSON file in either of two shapes.

**Array format** — a bare list of cards:

```json
[
  {"front": "API", "back": "Application Programming Interface"},
  {"front": "CDN", "back": "Content Delivery Network"}
]
```

**Object format** — a wrapper, with an optional deck name:

```json
{
  "name": "HTTP Status Codes",
  "cards": [
    {"front": "404", "back": "Not Found"},
    {"front": "429", "back": "Too Many Requests|Rate Limited"}
  ]
}
```

Details:

- `front` and `back` may also be spelled `question`/`answer` or
  `term`/`definition`, in any capitalisation.
- A `back` containing `|` accepts any of the alternatives, which is how
  `401` above accepts both `Unauthorized` and `Unauthorised`.
- A deck with no `name` is titled after its filename.
- Duplicate questions are a warning, not an error.

Check a deck before relying on it:

```bash
python main.py -f data/my_deck.json --validate
```

Bundled decks live in `data/`: `glossary.json` (array format),
`python_basics.json` (object format) and `http_status_codes.json` (object
format, with alternative answers).

## Saved progress

Every answer is recorded in `.flashcard_progress.json` in the working
directory, keyed on the question text so the history survives reordering or
extending a deck. Review it with:

```bash
python main.py -f data/glossary.json --stats
```

If that file is ever corrupted or hand-edited into nonsense, the application
says so and starts from an empty history rather than refusing to run.

## Configuration

Settings are resolved in this order, each overriding the one before:

1. Built-in defaults
2. A JSON config file: `--config PATH`, else `.flashcardrc.json` in the current
   directory, else the same name in your home directory
3. `FLASHCARD_*` environment variables
4. Command-line flags

```json
{
  "deck": "data/http_status_codes.json",
  "mode": "adaptive",
  "limit": 10,
  "color": true,
  "log_level": "INFO"
}
```

```bash
export FLASHCARD_MODE=spaced
export FLASHCARD_LIMIT=5
```

An unknown key in the config file is an error rather than a silently ignored
setting.

## Exporting a session

```bash
python main.py -f data/glossary.json --export md
python main.py -f data/glossary.json --export csv --export-path ~/quiz.csv
```

`json` gives the full session including every answer, `csv` gives one row per
question for a spreadsheet, and `md` gives a readable report. Without
`--export-path` the file lands in `exports/` under a timestamped name.

## Development

```bash
python -m pytest                                   # run the tests
python -m pytest --cov=. --cov-report=html         # coverage report -> htmlcov/
python -m black .                                  # format
python -m isort .                                  # organise imports
python -m flake8 .                                 # lint
python -m mypy .                                   # type check (strict)
python -m bandit -c pyproject.toml -r .            # security lint
```

Current state: **227 tests passing, 97% statement and branch coverage**, with
`flake8`, `mypy --strict` and `bandit` all clean.

## Project layout

```
main.py              Argument parsing, wiring, exit codes
models.py            Flashcard, CardResult, SessionStats, answer normalisation
data_loader.py       Deck loading and validation
quiz_engine.py       QuizMode strategies, QuizModeFactory, QuizSession
observers.py         Session event dispatch: console, logging, progress
progress_store.py    Cross-session history and SM-2 scheduling
config.py            Defaults, config file and environment resolution
stats_reporter.py    Session summary and json/csv/md export
ui.py                Colour, prompts, console presentation
utils/file_handler.py  Size-capped reads, atomic writes
data/                Flashcard decks
tests/               The pytest suite
docs/                Architecture notes, AI interaction log, final report
```

See [docs/architecture.md](docs/architecture.md) for how the pieces fit
together and why the design patterns are where they are.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Finished, including when you quit early |
| `1` | A problem you can fix: bad deck, bad flag, bad config |
| `2` | `argparse` rejected the command line |

A bad deck prints one readable line to standard error. It never prints a
traceback.
