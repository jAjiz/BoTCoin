# BoTCoin V2 – Roadmap

This document outlines the improvement areas and phased plan for the next iteration of BoTCoin. The goal is incremental, practical progress that improves maintainability, reliability, and developer experience without introducing unnecessary architectural complexity.

---

## 📋 Table of Contents

- [Current State](#-current-state)
- [Improvement Areas](#-improvement-areas)
- [Phased Roadmap](#-phased-roadmap)
  - [Phase 1 – Testing Foundation](#phase-1--testing-foundation)
  - [Phase 2 – Docker & Local Dev Environment](#phase-2--docker--local-dev-environment)
  - [Phase 3 – CI/CD Improvements](#phase-3--cicd-improvements)
  - [Phase 4 – Persistence Improvements](#phase-4--persistence-improvements)
  - [Phase 5 – Code Quality & Maintainability](#phase-5--code-quality--maintainability)
  - [Phase 6 – Configuration & Environment](#phase-6--configuration--environment)
  - [Phase 7 – Documentation & Project Presentation](#phase-7--documentation--project-presentation)
- [Out of Scope](#-out-of-scope)

---

## 🔍 Current State

BoTCoin V1 is a functional, modular trading bot with a clean separation of concerns across its packages (`core/`, `exchange/`, `trading/`, `services/`). The codebase is well-structured and documented via a comprehensive `README.md`.

Key gaps identified before starting V2 work:

| Area | Current Status |
|---|---|
| Testing | ❌ No unit or integration tests |
| Docker / local dev | ❌ No containerization |
| CI pipeline | ⚠️ Deploy-only (no test or lint step) |
| Persistence | ⚠️ JSON + CSV flat files (no migration path) |
| Type hints | ⚠️ Largely absent across the codebase |
| Environment setup | ⚠️ No `.env.example` template |
| Code quality tooling | ❌ No linter or formatter configured |
| Changelog / releases | ❌ No structured release history |

---

## 🗺️ Improvement Areas

### 1. Testing Strategy
The project currently has no automated tests. Adding a test suite is the highest-priority improvement because it directly enables safe refactoring, validates correctness of trading logic, and acts as a safety net for all future changes. The backtesting module (`trading/backtest.py`) already demonstrates the intent to validate behavior; this work extends that intent to the source modules themselves.

### 2. Docker-based Local Setup
Running the bot locally currently requires a correctly configured Python environment and live credentials. A Docker-based setup eliminates environment inconsistencies, simplifies onboarding, and makes it possible to run the bot or its components in an isolated, reproducible way without touching production credentials.

### 3. CI/CD Improvements
The current pipeline only deploys on push to `main`. There is no validation step—no linting, no tests—before code reaches production. Adding quality gates protects the live deployment and establishes a baseline for code health across every change.

### 4. Persistence Improvements
State is stored as JSON files and historical data as CSV files written directly to the `data/` directory. This is simple and effective for V1, but has limits: no schema enforcement, no migration path, and potential for silent data corruption. V2 should introduce a more robust storage layer while keeping operational simplicity.

### 5. Code Quality & Maintainability
The codebase lacks type annotations, has some duplicated patterns, and has no consistent formatter or linter enforced. Adding these incrementally improves readability, IDE support, and reduces cognitive overhead when modifying trading logic.

### 6. Configuration & Environment Setup
There is no `.env.example` template, making first-time setup harder than it needs to be. Configuration validation (`core/validation.py`) is good; it should be extended and surfaced more clearly to new contributors.

### 7. Documentation & Project Presentation
The `README.md` is thorough. V2 work should supplement it with a structured changelog, contribution guidelines, and clearer onboarding instructions that align with the Docker and testing improvements.

---

## 🚀 Phased Roadmap

Phases are ordered by impact and dependency. Each phase is independently releasable.

---

### Phase 1 – Testing Foundation

**Goal:** Establish a test suite that covers the core trading logic and enables safe refactoring throughout V2.

**Scope:**

- [ ] Add `pytest` as a development dependency
- [ ] Create a `tests/` directory mirroring the package structure
- [ ] Write unit tests for pure-logic functions in:
  - `trading/market_analyzer.py` (ATR calculation, pivot detection)
  - `trading/parameters_manager.py` (volatility level mapping, parameter calculation)
  - `trading/positions_manager.py` (position creation, trailing stop updates, close logic)
  - `trading/inventory_manager.py` (portfolio valuation, balance logic)
  - `core/validation.py` (configuration validation edge cases)
  - `core/utils.py` (utility functions)
- [ ] Use mocking (`unittest.mock`) to isolate exchange API calls from business logic tests
- [ ] Add a `pytest.ini` or `pyproject.toml` configuration for test discovery and reporting

**Success criteria:** Running `pytest` passes with no external network calls required.

---

### Phase 2 – Docker & Local Dev Environment

**Goal:** Allow the bot and its tooling to be run locally in a reproducible, credential-safe environment.

**Scope:**

- [ ] Write a `Dockerfile` targeting the production runtime (Python slim base image)
- [ ] Write a `docker-compose.yml` for local development that:
  - Mounts the `data/` directory as a volume for persistence
  - Loads credentials from a local `.env` file (not baked into the image)
  - Supports running the bot (`main.py`) and the modules that can be executed directly as scripts (`trading/market_analyzer.py` and `trading/backtest.py`, both of which have `if __name__ == "__main__"` entry points)
- [ ] Add a `.dockerignore` file to exclude `data/`, `.env`, `__pycache__`, and other non-essential files
- [ ] Update the `README.md` Quick Start section with Docker-based instructions

**Success criteria:** `docker compose up` starts the bot with a valid `.env` file, matching current manual setup behavior.

---

### Phase 3 – CI/CD Improvements

**Goal:** Add quality gates to the CI pipeline so that every push to `main` is validated before deployment.

**Scope:**

- [ ] Add a `lint` job to the GitHub Actions workflow that runs before deployment:
  - Use `ruff` for linting and formatting checks (fast, zero-config default)
- [ ] Add a `test` job that runs the `pytest` suite (from Phase 1)
- [ ] Make the `deploy` job depend on both `lint` and `test` passing
- [ ] Pin the GitHub Actions to specific commit SHAs (already done for `ssh-action`; apply consistently)
- [ ] Add a pull request check workflow that runs `lint` and `test` on every PR (separate from the deploy workflow)

**Success criteria:** A PR with a failing test or lint error cannot be merged without addressing the failure. The deploy workflow only triggers on a clean `main`.

---

### Phase 4 – Persistence Improvements

**Goal:** Make state storage more robust and introduce a clear data migration path, without adding unnecessary operational complexity.

**Scope:**

- [ ] Migrate active trade state and closed position history from JSON files to a local **SQLite** database (`data/botcoin.db`)
  - SQLite requires no external service, keeps the GCP free-tier deployment model intact, and adds schema enforcement
  - Retain CSV export for audit/analysis purposes (write-on-close)
- [ ] Define a simple schema for open positions and closed position history
- [ ] Write a one-time migration script (`scripts/migrate_json_to_sqlite.py`) to convert existing `data/trailing_state.json` and `data/closed_positions.json` on upgrade
- [ ] Update `core/state.py` to use the new storage layer via a thin abstraction so the rest of the codebase remains unchanged
- [ ] Add `data/botcoin.db` to `.gitignore`

**Success criteria:** The bot runs with SQLite as the persistence backend; existing JSON data can be migrated cleanly; the `data/` directory structure is documented.

---

### Phase 5 – Code Quality & Maintainability

**Goal:** Improve long-term maintainability through type hints, consistent formatting, and elimination of redundant patterns.

**Scope:**

- [ ] Add type annotations (`typing` module) to all public functions across:
  - `core/` modules
  - `exchange/kraken.py`
  - `trading/` modules
  - `services/telegram.py`
- [ ] Enforce formatting and linting via `ruff` locally (add `ruff` to `requirements-dev.txt`)
- [ ] Add a `pyproject.toml` to centralize tool configuration (`ruff`, `pytest`)
- [ ] Refactor repeated patterns (e.g., ATR file path construction) into shared utilities
- [ ] Review and align exception handling: distinguish between recoverable errors (log and continue) and fatal errors (log and exit)

**Success criteria:** `ruff check .` and `ruff format --check .` pass cleanly. All public function signatures carry type annotations.

---

### Phase 6 – Configuration & Environment

**Goal:** Make initial setup easier and reduce the risk of misconfiguration.

**Scope:**

- [ ] Add a `.env.example` file documenting every supported environment variable with its type, default value, and a short description
- [ ] Split `requirements.txt` into `requirements.txt` (runtime) and `requirements-dev.txt` (test, lint tooling)
- [ ] Validate numeric environment variables at load time with informative error messages (extend `core/validation.py` to cover all config values, including pair-specific params)
- [ ] Document the `data/` directory layout (what files are created, when, and what they contain) in the README

**Success criteria:** A new developer can clone the repo, copy `.env.example` to `.env`, fill in credentials, and have a working setup with no ambiguity.

---

### Phase 7 – Documentation & Project Presentation

**Goal:** Complement the existing README with structured release notes and contribution guidance.

**Scope:**

- [ ] Add a `CHANGELOG.md` following [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) format, tracking changes from the V2 milestone onwards (V1 history is not retroactively documented)
- [ ] Add a `CONTRIBUTING.md` with:
  - How to set up the local dev environment (Docker + `.env.example`)
  - How to run tests
  - Branch and PR conventions
- [ ] Add status badges to `README.md` (CI workflow status, Python version)
- [ ] Review and update the `README.md` Quick Start to reflect V2 setup (Docker, dev requirements)

**Success criteria:** A contributor unfamiliar with the project can set up, run tests, and submit a PR following only the documentation in the repository.

---

## 🚫 Out of Scope

The following are intentionally excluded from the V2 roadmap to keep scope realistic and aligned with the current nature of the project:

- **Multi-exchange support** – Kraken-only scope is maintained for V2
- **Web dashboard** – Telegram interface remains the primary monitoring surface
- **Database migration to PostgreSQL or external backends** – SQLite satisfies the reliability need without adding infrastructure
- **Async rewrite of the main trading loop** – The current threading model is adequate; a full async migration is high effort with limited benefit at this stage
- **Cloud infrastructure changes** – GCP free-tier VPS deployment model is retained; no Kubernetes or managed services

---

*This roadmap will be updated as phases complete. Follow-up issues will be opened for each phase.*
