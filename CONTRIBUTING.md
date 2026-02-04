# Contributing to Valence

Thank you for your interest in contributing to Valence! This document provides guidelines and instructions for contributing.

## Getting Started

### Prerequisites

- Python 3.10+
- PostgreSQL with pgvector extension (or use Docker)
- Git

### Development Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/orobobos/valence.git
   cd valence
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install in development mode:**
   ```bash
   pip install -e ".[dev]"
   ```

4. **Set up the database:**
   ```bash
   # Using Docker (recommended for development)
   docker run -d --name valence-db \
     -e POSTGRES_USER=valence \
     -e POSTGRES_PASSWORD=valence \
     -e POSTGRES_DB=valence \
     -p 5433:5432 \
     pgvector/pgvector:pg16

   # Or configure your existing PostgreSQL with pgvector
   ```

5. **Set environment variables:**
   ```bash
   export VALENCE_DB_URL="postgresql://valence:valence@localhost:5433/valence"
   export OPENAI_API_KEY="your-key-here"  # For embeddings
   ```

## Code Style

We use the following tools to maintain code quality:

### Formatting with Black

```bash
black src/ tests/
```

### Linting with Ruff

```bash
ruff check src/ tests/
ruff check --fix src/ tests/  # Auto-fix issues
```

### Type Checking with mypy

```bash
mypy src/
```

### Running All Checks

```bash
# Run all quality checks
black --check src/ tests/
ruff check src/ tests/
mypy src/
pytest
```

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=valence

# Run specific test file
pytest tests/test_db.py

# Run with verbose output
pytest -v
```

## Submitting Changes

### Pull Request Process

1. **Fork the repository** and create your branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** and ensure:
   - All tests pass (`pytest`)
   - Code is formatted (`black`)
   - No linting errors (`ruff check`)
   - Type hints are correct (`mypy`)

3. **Write clear commit messages:**
   ```
   feat: add new query ranking algorithm
   
   - Implement multi-signal ranking
   - Add recency weighting option
   - Update documentation
   ```

4. **Push to your fork** and open a Pull Request

5. **Describe your changes** in the PR description:
   - What problem does this solve?
   - How did you test it?
   - Any breaking changes?

### Commit Message Convention

We follow conventional commits:

- `feat:` - New features
- `fix:` - Bug fixes
- `docs:` - Documentation changes
- `test:` - Test additions/changes
- `refactor:` - Code refactoring
- `chore:` - Maintenance tasks

## Code of Conduct

We are committed to providing a welcoming and inclusive environment. A formal Code of Conduct will be added soon. In the meantime, please:

- Be respectful and inclusive
- Welcome newcomers
- Focus on constructive feedback
- Assume good intentions

## Questions?

- **GitHub Issues:** For bugs and feature requests
- **GitHub Discussions:** For questions and ideas (coming soon)

## License

By contributing to Valence, you agree that your contributions will be licensed under the MIT License.
