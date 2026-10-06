# Flashcard Quizzer: Project Starter

This is the starter for **The Flashcard Quizzer**, a command-line application that loads flashcards from a JSON file and quizzes you in sequential, random, or adaptive mode. You won't write the application by hand. You'll direct an AI coding agent to build it, review what it produces, and refine it until it meets the specification.

The full specification (functional requirements, design patterns, required tests, and Definition of Done) is on the project's **Instructions** page in the classroom. This README explains what the starter gives you and how to get going.

## What's in the starter

```
starter/
├── main.py                 # Empty. Your entry point.
├── data/                   # Sample flashcard decks
│   ├── glossary.json       # Array format: [{"front": ..., "back": ...}]
│   └── python_basics.json  # Object format: {"cards": [...]}
├── utils/                  # Your helper modules go here
├── tests/                  # Empty. Your pytest suite goes here
├── docs/
│   ├── ai_edit_log.md      # AI interaction log (required, 5+ entries)
│   ├── report_template.md  # Final report template (required, 1,000-1,500 words)
│   └── design_patterns.md  # Pattern reference
├── ai_guidance/            # Prompting and code review guides
├── .claude/                # Claude Code configuration and slash commands
└── requirements.txt        # Quality tools: pytest, black, flake8, mypy, ...
```

`main.py`, `utils/` and `tests/` are deliberately empty. Building them is the project. Keep the folder structure: your agent uses it to separate concerns.

The two sample decks use the two JSON formats your loader must support. You can add your own decks to `data/`.

## Getting started

1. **Install the quality tools.**

   In the provided workspace:
   ```bash
   cd /voc/work/project/starter
   python -m pip install -r requirements.txt
   ```

   On your own computer, create and activate a virtual environment first, then install:
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   python -m pip install -r requirements.txt
   ```

2. **Start your AI agent** from this folder (for example, `claude`) and work through the milestones on the Instructions page.

## When you're done

These commands should work (the flags are part of the specification):

```bash
python main.py --help
python main.py --mode sequential --file data/glossary.json
python main.py -m adaptive -f data/python_basics.json
```

And these checks should pass:

```bash
python -m pytest --cov=. --cov-report=html   # target: >80% coverage
python -m black --check .
python -m flake8 .
python -m mypy .
```

## What to submit

Check the Instructions page and the rubric for the full list. In short:

- Your complete source code, the `tests/` suite, and the `data/` decks
- `docs/ai_edit_log.md` with at least 5 detailed AI interactions
- The final report, written from `docs/report_template.md` (1,000-1,500 words)
- This README, rewritten to describe **your** application: features, setup, and usage examples

## License

[License](../../LICENSE.txt)
