# Contributing

## Setup

Python 3.11. On Linux:

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu   # optional: CPU-only torch
pip install -r requirements.txt -r requirements-dev.txt eclipse-sumo==1.27.1
export SUMO_HOME="$(python -c 'import sumo; print(sumo.SUMO_HOME)')"   # add this line to .venv/bin/activate
python scripts/setup/check_setup.py
```

On Windows, see [Setup in the README](README.md#setup).

## Branches and pull requests

- Don't commit to `master` directly. Branch off the latest `master`:
  `feature/<name>`, `fix/<name>`, `docs/<name>` or `chore/<name>`.
- Keep a pull request to one change, and say in its description what changed and why.
- If the change affects results (network, observation, reward, training settings), say which runs need to be
  redone. Checkpoints trained before the change no longer match.
- CI runs the tests on every pull request; it has to pass before merging.

## Tests and linting

```bash
python -m pytest -q
ruff check <files you changed>
```

The repo doesn't pass `ruff check .` cleanly yet, so the rule is: don't add new warnings in the files you touch.
Add or update tests in `tests/` for new behaviour.
