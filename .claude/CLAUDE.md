# Claude Configuration for AI-Assisted Development Course

This document configures Claude to provide optimal assistance for the AI-assisted development course project.

## Project Context

This is a learning project for a software engineering course focused on AI-assisted development. Students are building a Python application while learning to effectively collaborate with AI coding assistants.

The application is **the Flashcard Quizzer**: a command-line app that loads flashcards from JSON and quizzes the user in sequential, random, or adaptive mode. The full specification is on the project Instructions page in the classroom.

## Course Objectives

Students will:
- Build a functional Python application with clear requirements and constraints
- Collaborate effectively with AI assistants while maintaining code quality
- Apply software engineering principles including design patterns and separation of concerns
- Develop and maintain a comprehensive unit test suite
- Document their AI collaboration process and learning journey

## Student Responsibilities

### Code Quality
- Review and understand all AI-generated code before accepting it
- Test AI-generated code thoroughly with various inputs and edge cases
- Refactor code for clarity, maintainability, and adherence to project standards
- Implement proper error handling and input validation
- Follow Python coding conventions (PEP 8) and project style guidelines

### Software Engineering Practices
- Apply appropriate design patterns where beneficial
- Maintain separation of concerns and modular code structure
- Write comprehensive unit tests with good coverage (>80%)
- Use proper version control practices with descriptive commit messages
- Document code with clear docstrings and comments where necessary

### AI Collaboration
- Write specific, clear prompts that provide context and requirements
- Critically evaluate AI responses for correctness, security, and efficiency
- Document all AI interactions in the provided AI edit log
- Ask for explanations when AI logic is unclear
- Iterate on AI suggestions to improve code quality

### Documentation
- Maintain detailed logs of AI interactions and decisions
- Update project documentation as features are added
- Complete the final project report with reflections on AI collaboration
- Document any challenges faced and solutions implemented

## AI Assistant Guidelines

### Code Generation
- Provide clean, well-documented code that follows Python best practices
- Include type hints and proper error handling
- Suggest appropriate design patterns when beneficial
- Ask clarifying questions if requirements are unclear

### Code Review
- Point out potential security vulnerabilities
- Suggest improvements for readability and maintainability
- Identify edge cases that need testing
- Recommend refactoring opportunities

### Educational Support
- Explain complex concepts and design decisions
- Provide examples of best practices
- Suggest learning resources when appropriate
- Help debug issues and understand error messages

## Project Structure

The project follows this organization:
- `main.py` - Application entry point
- `utils/` - Reusable utility modules
- `data/` - Sample flashcard decks in JSON
- `tests/` - Comprehensive unit test suite
- `docs/` - Project documentation and templates
- `ai_guidance/` - AI collaboration best practices
- `.claude/` - Claude-specific configuration

## Development Tools

Students should use these tools for code quality:
- **pytest** for testing
- **black** for code formatting
- **isort** for import organization
- **flake8** for linting
- **mypy** for type checking

## Common Commands

Students can use these commands during development:
- `python main.py` - Run the application
- `python -m pytest` - Run all tests
- `python -m pytest --cov=. --cov-report=html` - Run tests with coverage
- `python -m black .` - Format code
- `python -m isort .` - Organize imports
- `python -m flake8 .` - Check linting
- `python -m mypy .` - Type checking

Install packages with `python -m pip install -r requirements.txt`, and run every tool through `python -m` as listed above. In the provided workspace, install directly; do not create a virtual environment.

## Assessment Criteria

Projects will be evaluated on:
1. **Functionality** - Does the application work correctly?
2. **Code Quality** - Is the code well-structured and maintainable?
3. **Testing** - Are there comprehensive tests with good coverage?
4. **AI Collaboration** - Did the student effectively work with AI while maintaining quality?
5. **Documentation** - Are AI interactions and decisions well-documented?

## Best Practices for AI Collaboration

### Effective Prompting
- Be specific about requirements and constraints
- Provide context about the existing codebase
- Ask for explanations of complex logic
- Request code reviews and improvement suggestions

### Code Review Process
- Always understand AI-generated code before using it
- Test thoroughly with various inputs and edge cases
- Check for security vulnerabilities and edge cases
- Refactor for clarity and maintainability

### Learning Approach
- Use AI as a learning tool, not a replacement for understanding
- Ask follow-up questions to deepen understanding
- Experiment with different approaches
- Document lessons learned throughout the process

## Remember

The goal is not just to build a working application, but to learn effective AI collaboration while maintaining high software engineering standards. Students should:
- Take ownership of their code quality
- Use AI as a powerful tool while exercising good judgment
- Focus on learning and understanding, not just completion
- Document their journey for future reference and assessment

Success in this project comes from thoughtful collaboration with AI, not from accepting AI suggestions without review and understanding.