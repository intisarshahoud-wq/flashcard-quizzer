# AI-Assisted Development Project Report

**Student Name:** Intisar Shah
**Project Title:** Flashcard Quizzer — a modular CLI flashcard trainer
**Date:** 6 October 2026

## Executive Summary

The Flashcard Quizzer is a terminal application that loads flashcards from JSON
and quizzes the user in one of four modes. It validates decks, grades answers
forgivingly, remembers what the user keeps getting wrong across sessions, and
reports results on screen or as a JSON, CSV or Markdown export.

The finished project is 1,082 statements across ten modules and 227 tests at 97%
statement and branch coverage, with `flake8`, `mypy --strict` and `bandit` all
clean and no third-party runtime dependency.

I wrote almost none of it by hand. My role was to specify, review and correct:
breaking the brief into phases, writing prompts precise enough to produce
reviewable code, reading the result against the review checklist, and deciding
what to keep. The eight interactions where the generated code and the shipped
code diverged are documented in `docs/ai_edit_log.md`.

## Project Overview

### Problem Statement

New engineers face a wall of vocabulary — acronyms, status codes, keywords —
and existing tools are web apps that pull attention out of the terminal. The
brief asks for a lightweight internal tool that runs where the work happens,
reads plain JSON a team can version-control, and is clean enough to extend.

### Solution Approach

The architecture follows the dependency direction strictly: `models.py` imports
nothing from the project, `main.py` imports almost everything, and nothing
imports upward. Ten modules each hold one responsibility — loading, card
selection, presentation, reporting, persistence, configuration, file access.

The decisive choice was giving the engine two protocols instead of concrete
collaborators. `AnswerProvider` abstracts where answers come from and
`DifficultyOracle` abstracts card history, so nothing in `quiz_engine.py` calls
`input()`, prints, or touches the disk. That is why the engine reaches 97%
coverage without mocking builtins.

**Stack:** Python 3.10+, standard library only at runtime; `pytest`, `black`,
`isort`, `flake8`, `mypy` and `bandit` for development.

### Final Features

- [x] Both JSON deck shapes, validated with errors that name the bad card
- [x] Case-, whitespace- and Unicode-insensitive grading; alternative answers
- [x] Four quiz modes: sequential, random, adaptive, spaced repetition
- [x] Summary: totals, accuracy, streak, timings, review list
- [x] Cross-session progress keyed on question text
- [x] Export to JSON, CSV or Markdown
- [x] Layered configuration: defaults, file, environment, flags
- [x] `--validate` deck checker, `--stats` viewer, structured logging

## AI Collaboration Experience

### AI Tools Used

- [x] Claude (Claude Code, Opus, in the terminal)

### Collaboration Workflow

I worked in eight phases, each ending at a commit: environment, data layer,
engine, CLI, extra features, quality gates, tests, documentation.

Prompts were written as specifications rather than requests, and that mattered
more than anything else I did. Asking for "good error handling" produced generic
messages; enumerating six failure modes — missing file, malformed JSON, wrong
top-level shape, empty deck, non-object card, missing side — produced messages
that name the offending card by position.

Review used the project's `code_review_checklist.md` plus three questions I
asked of every generated module: what is the worst input, what happens on the
path I never described, and does this run anywhere but my machine. Every real
defect came from one of those three.

Validation was layered — tools, then tests, then reading. Each layer caught what
the others missed: one defect was found by `bandit`, one by pytest's warning
configuration, one only by reading the code.

### Most Valuable AI Interactions

**Adaptive mode could not terminate.** I asked for a mode that re-asks cards the
user gets wrong. The generated code did exactly that, with no bound: a user who
never answers correctly loops forever. The fault was in my specification, and
the AI identified it immediately when I asked "what if the user never gets it
right?" The fix, a `MAX_REPEATS` cap on the base class, has a test named after
the failure.

**A `colorama` dependency I rejected.** Asked for coloured Windows output, the
AI reached for the conventional library. I re-prompted for raw ANSI escapes with
a `ctypes` call to enable virtual terminal processing, plus the `NO_COLOR` and
TTY checks it had omitted. Forty lines of standard library replaced an
install-time requirement.

**A dead constant both linters accepted.** `ui.py` defined `SKIP_WORDS` and
never used it, so typing `skip` was graded as a literal answer and stored in the
progress file as a real guess. `flake8` and `mypy` passed — an unused module
constant is valid, well-typed Python. It surfaced only from reading.

### Challenges with AI Collaboration

The consistent weakness was blindness to cases I had not named. The AI follows a
specification literally, which is a strength when the specification is complete
and a liability when it is not. It also optimises for the error on screen: when
`mypy` flagged an unused `type: ignore` on a Windows-only `ctypes` call, its
suggestion was to delete the comment — correct on my machine, broken on a
grader's Linux box.

What it did not struggle with was volume. Given stable interfaces, it generated
227 tests across seven modules in a handful of prompts.

## Software Engineering Practices

### Code Quality Measures

- [x] `black` and `isort` (profile `black`), 88 columns
- [x] `flake8` zero errors, `max-complexity = 10`
- [x] `mypy --strict` clean, including the tests
- [x] `bandit` clean, with two documented `# nosec` suppressions
- [x] Google-style docstrings throughout
- [x] Every user-facing failure is one readable line, never a traceback

### Testing Strategy

227 tests across seven modules: unit tests per module, integration tests driving
`QuizSession` with scripted input, and CLI tests calling `main.run()` with real
argument lists. Coverage is 97% of statements and branches against an 80%
requirement — a consequence of the protocol-based design rather than a target I
chased.

I did not use strict TDD. Tests followed each module, which made them a review
pass: three of the eight logged defects were found while writing tests rather
than running them. Setting `filterwarnings = ["error"]` promoted a
`ResourceWarning` into a failure and exposed a leaked file handle in
`configure_logging`.

### Design Patterns Used

- **Strategy** (`QuizMode` and four subclasses). The brief's three modes are
  three algorithms for one decision: which card comes next. The pattern earned
  its keep concretely — `SpacedRepetitionMode` was added after the engine, CLI
  and tests were finished and required no change to any of them.
- **Factory** (`QuizModeFactory`). Turns the `--mode` string into a configured
  strategy. Registration is a decorator, and `--mode`'s choices, the `--help`
  epilogue and `--list-modes` all read the registry, so registering a class is
  the complete cost of adding a mode.
- **Observer** (`SessionSubject` and three observers). Printing feedback,
  logging and updating saved history are unrelated reactions to one event.
  `--no-progress` is implemented by not attaching an observer, and each
  notification is isolated so a failing observer cannot end someone's quiz.

### Code Structure

`utils/file_handler.py` is the only module touching the filesystem, so the size
cap, encoding and atomic-write behaviour are defined once. Refactoring moved the
re-queue logic onto `QuizMode`, so both history-aware modes share the
termination guarantee.

## Technical Challenges and Solutions

**Progress that survives a changing deck.** An index-keyed history breaks when a
card is inserted, so cards are keyed on normalized question text. Records then
survive reordering and extension. The cost is that duplicate questions merge,
surfaced as a load-time warning rather than left silent.

**A rewritten file that must not be lost.** The progress file is rewritten after
every session, so a crash mid-write could truncate it. `write_json` writes to a
temporary file and `os.replace`s it into position. A test writes an
unserialisable payload over a good file and asserts the original survives.

## Code Quality Analysis

| Metric | Value |
| --- | --- |
| Application statements | 1,082 |
| Tests | 227 |
| Coverage (statement and branch) | 97% |
| Modules / classes / functions | 10 / 19 / 130 |
| `flake8` / `mypy --strict` / `bandit` | 0 / 0 / 0 |

**Self-assessment.** Readability 4 — consistent structure and docstrings that
explain reasoning, though `main.py` carries more wiring than I would like.
Maintainability 5 — adding a quiz mode is one class. Test quality 4 — strong
coverage, but some CLI tests assert on output text. Documentation 5.

## Learning Outcomes and Reflection

The technical skill I developed was treating testability as a design property.
Injecting the clock, the random generator, the input source and the history
provider made exhaustive testing cheap; I would have reached for mocks before
and got a worse result.

On AI collaboration, the central lesson is that reviewing generated code is
mostly the discipline of asking what the code was never told about. Every real
defect here sits in a case I had not named: the user who never gets a card
right, the file opened and never closed, the operating system I was not
developing on.

What worked best was writing prompts as specifications and running tools that
disagree. `mypy` accepted the `assert` that `bandit` rejected; `bandit` raised
two findings I judged wrong here. No tool's verdict was final, and choosing
which to act on stayed with me.

What I would change: configure the strict tooling before generating any code.
Every defect those tools caught was already committed by the time I pointed them
at it. With more time I would add a review mode covering overdue cards across
every deck, deck merging, and a `tomllib`-based config format.
