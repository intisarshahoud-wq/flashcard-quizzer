# AI Edit Log

A record of the AI interactions that produced the Flashcard Quizzer, and of
what I changed, challenged or rejected in what came back.

**AI tool used throughout:** Claude Code (Opus) in the terminal.
**Project:** Flashcard Quizzer CLI (Udacity cd14602).

Eight entries follow. Each one is a point where the AI output and the code that
shipped were not the same thing.

---

## 2026-10-06 — Entry 1: Making the loader's error messages actionable

**Context:** Phase 1 of the project. The deck loader has to accept two JSON
shapes and fail gracefully. The brief is explicit that a malformed file must
produce a helpful message, not a stack trace.

**Prompt/Request:**

> Create `data_loader.py`. Load flashcards from a JSON file, supporting both a
> bare list of `{"front", "back"}` objects and a `{"cards": [...]}` wrapper.
> Raise a custom `FlashcardLoadError` with a user-facing message for: file
> missing, malformed JSON, top level is neither shape, deck is empty, a card is
> not an object, a card missing either side. Use type hints throughout.

**AI Response:** A working loader with `load_flashcards()` and
`FlashcardLoadError`. Both shapes handled, all six failure cases caught. The
messages, though, were generic — the missing-field case said
`"Invalid card format"` with no indication of *which* card.

**Changes Made:**

- Added the card's 1-based position to every card-level message, via an
  `_ordinal()` helper, so an error reads `card #7 is missing its back side`.
- Added the offending key and its actual type to the wrong-type message:
  `card #1 has a non-text back side: "back" is int, expected text`.
- Passed the JSON syntax error's line and column through from
  `json.JSONDecodeError` rather than discarding them.
- Added a non-fatal warnings channel for duplicate questions, which are legal
  JSON but silently merge in adaptive mode because history is keyed on the
  question text.

**Reasoning:** "Invalid card format" tells a user that something is wrong and
nothing about where. In a 200-card deck that is nearly useless. Every message
in the loader now names a position, a field, or a line number — something the
user can act on. The duplicate case is a warning rather than an error because
the quiz still runs correctly; refusing to load would be disproportionate.

**Outcome:** Ten parametrised cases in `test_flashcard_loader.py` assert on the
specific wording. `python main.py -f broken.json` prints one line and exits 1.

**Lessons Learned:** The AI reliably produced *correct* error handling and
consistently under-specified *useful* error handling. Asking for "good error
messages" produced generic ones; naming the failure cases one by one in the
prompt produced far better code.

---

## 2026-10-06 — Entry 2: Pushing back on an unbounded adaptive loop

**Context:** Phase 2. Adaptive mode has to prioritise cards the user got wrong
and re-ask them within the session.

**Prompt/Request:**

> Implement `AdaptiveMode` as a `QuizMode` subclass. Order the deck hardest
> first using the stored difficulty score, and when the user answers a card
> incorrectly, put it back into the queue so it is asked again later in the
> session.

**AI Response:** Exactly what I asked for. `record_result()` checked
`if not correct` and re-inserted the card a couple of positions ahead in the
queue.

**Changes Made:** I rejected the first version and asked a follow-up:

> What happens if the user never answers that card correctly?

The answer was that the quiz never ends. I had it add a `MAX_REPEATS` cap and a
`_repeats` counter per card key, and moved the re-queue logic into a shared
`_requeue()` on the base class so the spaced-repetition mode inherits the same
guarantee.

**Reasoning:** A quiz that cannot terminate is the worst defect this program
could have — worse than a wrong statistic, because the user cannot get out of it
without killing the process. The cap converts "repeat until correct" into
"repeat at most twice", which is still the behaviour the brief asks for.

**Outcome:** `test_adaptive_mode_terminates_when_always_wrong` answers every
question wrong and asserts the session ends, with an in-loop assertion that
fails fast rather than hanging the suite if the cap is ever removed.

**Lessons Learned:** The AI implemented my specification faithfully, and my
specification had a hole in it. It did not volunteer the termination problem,
but it identified it immediately and correctly when asked directly. The useful
habit is asking "what is the worst input for this?" about anything with a loop
in it — that question is cheap and it found a real bug here.

---

## 2026-10-06 — Entry 3: Rejecting a `colorama` dependency

**Context:** Phase 3 requires coloured output — green for correct, red for
incorrect — and the project has to run on Windows.

**Prompt/Request:**

> Write `ui.py` with a Console class that writes coloured output: green for
> correct, red for incorrect. It must work on Windows.

**AI Response:** A clean implementation built on `colorama`, with
`colorama.init()` at import and `Fore.GREEN` / `Fore.RED` constants.

**Changes Made:** Rejected and re-prompted:

> Rewrite it with no third-party dependency. Use raw ANSI escapes and enable
> virtual terminal processing on Windows through ctypes. Suppress colour when
> the stream is not a TTY, when `NO_COLOR` is set, and when `TERM=dumb`.

The replacement is about forty lines: a dict of eight escape codes, one
`SetConsoleMode` call via `ctypes`, and a `supports_color()` check.

**Reasoning:** The whole application otherwise imports only the standard
library, which means it runs on a bare Python install with nothing to install
first. Adding `colorama` to get eight escape sequences would have traded that
away for very little. The `NO_COLOR` and TTY checks were my additions — the
first version would have written escape codes into a redirected file.

**Outcome:** `requirements.txt` is development tooling only. `ui.py` is at 100%
coverage, and `test_ui.py` asserts colour is suppressed in all four cases.

**Lessons Learned:** The AI reached for the conventional library without
weighing whether the dependency was worth it. That judgement — what a dependency
costs a project — is not something it volunteered, and it is exactly the kind of
decision that stays with the engineer.

---

## 2026-10-06 — Entry 4: Dead constant found in review

**Context:** Reviewing `ui.py` against the project's
`ai_guidance/code_review_checklist.md`, specifically "is the code easy to
understand" and "are all inputs validated".

**Prompt/Request:** Part of the `ui.py` generation prompt asked for quit words
and skip words:

> The user can type "exit" or "quit" to stop. "skip" or "?" should pass on a
> card without answering it.

**AI Response:** The module defined both sets as module constants:

```python
QUIT_WORDS: Final[frozenset[str]] = frozenset({"exit", "quit", ":q"})
SKIP_WORDS: Final[frozenset[str]] = frozenset({"skip", "pass", "?"})
```

`ask()` checked `QUIT_WORDS` and returned `None`. It never referenced
`SKIP_WORDS` at all.

**Changes Made:** Added the missing branch, returning an empty string rather
than the typed word:

```python
if normalized in SKIP_WORDS:
    return ""
```

**Reasoning:** Without the branch, typing `skip` submitted the literal string
`"skip"` as an answer. It was marked incorrect — the right outcome by accident —
but the word was then stored in the progress file and printed in the exported
report as though the user had seriously guessed "skip". Returning `""` records
what actually happened: no answer given. The Markdown exporter renders that as
`_(skipped)_`.

Note that neither `flake8` nor `mypy` flagged this. An unused module-level
constant is valid Python and well-typed. It only surfaced by reading the code
against the checklist.

**Outcome:** Four parametrised cases in `test_ui.py` cover the skip words, and
`test_markdown_marks_a_skipped_answer` covers the report rendering.

**Lessons Learned:** The gap between "the linters pass" and "the code does what
was asked" is real. This is the clearest example in the project of a defect that
only a human reading the code could have caught, and it is why the review step
is not optional.

---

## 2026-10-06 — Entry 5: A resource leak the test suite caught

**Context:** Writing `test_cli.py`, specifically a test that `--log-file`
actually writes to the named file.

**Prompt/Request:**

> Write a test that `configure_logging` with a log file path writes log records
> to that file.

**AI Response:** A straightforward test: configure logging, emit a record,
flush, assert the text is in the file.

It failed — not on the assertion, but with:

```
PytestUnraisableExceptionWarning: Exception ignored in:
<_io.FileIO name='...run.log' mode='ab' closefd=True>
```

**Changes Made:** Two changes, one in the test and one in the application.

The real fault was in `main.configure_logging`, which detached the previous
handler without closing it:

```python
for existing in list(root.handlers):
    root.removeHandler(existing)      # before
    existing.close()                  # added
```

The test then restores stderr logging in a `finally` block rather than clearing
the handler list by hand.

**Reasoning:** `removeHandler` only detaches; the underlying file stays open
until garbage collection. Every call to `configure_logging` leaked a descriptor.
In a short CLI run that is invisible, which is precisely why it was worth fixing
— it would never have shown up in manual testing.

This was found because `pyproject.toml` sets `filterwarnings = ["error"]`, which
promotes `ResourceWarning` to a failure. I had set that deliberately when
configuring pytest.

**Outcome:** `test_configure_logging_writes_to_a_file` passes, and the handler
is closed on every reconfiguration.

**Lessons Learned:** Strict test configuration earns its keep. The AI wrote both
the leaky code and the test that exposed it; neither it nor I would have noticed
without `filterwarnings = error` turning a warning into a failure.

---

## 2026-10-06 — Entry 6: Rejecting `assert` as type narrowing

**Context:** Running `bandit` across the finished code as a final security pass.

**Prompt/Request:** Earlier, while writing `main.show_stats`:

> Build a table of per-card progress. Only include cards that have actually
> been answered.

**AI Response:** A list comprehension that filtered on a possibly-`None` record,
then an `assert` inside the loop to satisfy `mypy`:

```python
answered = [(card, record) for card, record in tracked if record and record.seen]
for card, record in answered:
    assert record is not None  # narrowed by the filter above
```

`mypy --strict` was happy. `bandit` was not: **B101, assert_used**.

**Changes Made:** Replaced the comprehension and the assert with an explicitly
typed accumulator loop:

```python
answered: list[tuple[Flashcard, CardProgress]] = []
for card in deck.cards:
    record = store.records.get(card.key)
    if record is not None and record.seen:
        answered.append((card, record))
```

**Reasoning:** `assert` statements are removed entirely when Python runs with
`-O`. Using one to carry a type guarantee means the guarantee silently
disappears in exactly the configuration where you would least want it to. The
annotated accumulator gives `mypy` the same information without executing
anything at runtime.

I also reviewed `bandit`'s two other findings — `B311`, the standard
pseudo-random generator — and rejected those. Shuffling a flashcard deck is not
a security decision, and `--seed` reproducibility depends on a deterministic
generator. Both sites now carry a `# nosec B311` with a comment explaining the
reasoning, rather than being silenced globally.

**Outcome:** `bandit -c pyproject.toml -r .` reports zero issues at every
severity. Two suppressions, both justified in a comment at the suppression site.

**Lessons Learned:** Running several tools matters because they disagree.
`mypy` accepted the assert; `bandit` rejected it; `bandit` also raised two
findings that were wrong for this context. Neither tool's verdict is the final
word, and deciding which findings to act on was a judgement I had to make.

---

## 2026-10-06 — Entry 7: Code that type-checks on one platform only

**Context:** Getting `mypy --strict` clean across the project.

**Prompt/Request:**

> Enable ANSI escape handling on Windows from `ui.py`.

**AI Response:** The `ctypes` approach, with a `# type: ignore[attr-defined]`
on the `ctypes.windll` access.

Running `mypy` on Windows then reported:

```
ui.py:52: error: Unused "type: ignore" comment  [unused-ignore]
```

My first instinct — and the AI's first suggestion when I pasted the error — was
to delete the comment. That fixed it locally.

**Changes Made:** I reverted that fix. `ctypes.windll` exists only on Windows,
so `mypy` on Linux or macOS needs the ignore, while `mypy` on Windows flags it
as unnecessary. Deleting it would have made the project type-check on my machine
and fail on a grader's.

The fix is a scoped override in `pyproject.toml`:

```toml
[[tool.mypy.overrides]]
module = "ui"
warn_unused_ignores = false
```

**Reasoning:** The two platforms genuinely disagree about whether that ignore is
needed, so suppressing the unused-ignore warning for this one module is the only
resolution that is correct on both. Scoping it to `ui` rather than disabling the
check globally keeps a genuinely stale ignore anywhere else still detectable.

**Outcome:** `mypy --strict` passes on Windows, and the ignore the other
platforms require is still present.

**Lessons Learned:** The AI optimised for the error in front of it. Neither its
first fix nor my first instinct accounted for the fact that the code would be
checked on a different operating system than the one I was using. "Make the
error go away" and "make the code correct" are not the same instruction, and the
difference only showed up when I thought about where else this would run.

---

## 2026-10-06 — Entry 8: A test that asserted on formatting instead of behaviour

**Context:** `test_cli_quit_word_stops_the_quiz` failed after passing in an
earlier form.

**Prompt/Request:**

> Write an integration test: the user answers the first question, types "exit"
> at the second, and the summary should show one question answered and say the
> session ended early.

**AI Response:** A test asserting on the literal summary line:

```python
assert "Total questions  1" in output
```

It failed:

```
assert 'Total questions  1' in '...Total questions   1...'
```

**Changes Made:** The application was right and the test was wrong. The summary
pads its label column to the widest label present, and the timing rows
(`Average per card`, 16 characters) are wider than `Total questions`. The
earlier passing test had used `--no-timer`, so the padding differed. Fixed by
comparing on collapsed whitespace:

```python
# The summary pads its label column to the widest label, which depends on
# whether timing rows are shown, so compare on collapsed whitespace.
output = " ".join(capsys.readouterr().out.split())
assert "Total questions 1" in output
```

**Reasoning:** The behaviour under test is "one question was counted". The exact
number of spaces is presentation, and a test that fails when a label is renamed
is a test that will get deleted rather than fixed. I deliberately did not change
the padding logic to make the test pass — the alignment is correct, and bending
the application to suit a brittle assertion would have been the wrong direction.

**Outcome:** The test passes and still fails if the count is wrong.

**Lessons Learned:** The AI wrote assertions against the exact output it had
just seen, which is reasonable and also brittle. Deciding what a test is really
for — the behaviour, not the rendering — was the part I had to supply, and it is
the same judgement as deciding whether a failing test means the code is wrong or
the test is.

---

## Summary Statistics

- **Total AI interactions:** 40+ substantive prompts across eight development
  phases (setup, data layer, engine, CLI, extras, quality, tests, docs)
- **Lines of AI-generated code used:** ~2,430 (1,082 application, ~1,350 tests)
- **Lines of AI-generated code modified or rejected:** ~180, across the eight
  entries above plus formatting and lint corrections
- **Most helpful AI interaction:** Generating the full `pytest` suite. Once the
  engine depended on protocols rather than concrete classes, the AI produced
  227 tests at 97% coverage in a handful of prompts — work that would have taken
  me far longer by hand and that I could verify by running it.
- **Most challenging AI interaction:** The adaptive mode termination problem
  (Entry 2). The generated code matched my prompt exactly and was still wrong,
  which meant the fault was in my specification rather than in the output.
- **Biggest lesson learned:** The AI is very good at the path I describe and
  largely blind to the paths I do not. Every real defect in this log sits in a
  case I had not named: the user who never gets a card right, the file opened
  and never closed, the operating system I was not developing on. Reviewing
  generated code is mostly the discipline of asking what it was never told
  about.

## Reflection Questions

**1. What types of tasks did AI help with most effectively?**
Mechanical breadth. Test suites, docstrings, parametrised edge cases, argparse
plumbing, format conversions. Given a clear interface it produced a large volume
of correct, consistent code faster than I could type it.

**2. Where did you need to make the most modifications?**
Anywhere judgement was involved rather than translation: error message quality,
whether a dependency is worth its cost, what a test is actually asserting, which
static-analysis findings deserve to be acted on.

**3. What patterns did you notice in AI strengths and weaknesses?**
It follows a specification very literally. That is a strength when the
specification is complete and a weakness when it is not — the infinite loop in
Entry 2 was a faithful implementation of what I asked for. It also optimises
for the error in front of it (Entry 7) without considering a wider context it
was never given.

**4. How did your prompting technique improve?**
From outcomes to enumerated cases. "Handle errors gracefully" produced generic
messages; listing the six failure modes produced specific ones. I also started
asking adversarial follow-ups — "what happens if this never succeeds?" — which
is what surfaced the termination bug.

**5. What would you do differently?**
Set the strict tooling up before generating any code rather than after.
`filterwarnings = error`, `mypy --strict` and `bandit` each caught something
real, and every one of those defects existed in committed code for a while
before the tool that caught it was pointed at it.
