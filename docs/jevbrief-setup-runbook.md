# jevbrief setup — Runbook for Claude Code
> Claim the jevbrief name on GitHub, PyPI, and npm, then start building v0.1.

This runbook takes an empty machine to a public `jevbrief` repo with placeholder packages on PyPI and npm, then hands off to `jevbrief-spec.md` to start the real build. The owner is **parthkomalwad**. Target ship date for v0.1.0 is **Thursday, September 24, 2026**.

---

## Instructions for Claude Code

- Work through the steps in order. Do not skip ahead.
- Steps marked **HUMAN** need the owner to act (logins, 2FA, tokens). Stop, print exactly what the owner must do, and wait for them to confirm before continuing.
- Never print, echo, log, or commit any token or password. Read secrets only from environment variables or interactive prompts.
- The package name is exactly `jevbrief` (j-e-v-b-r-i-e-f). Check spelling before every publish. Package names cannot be renamed later.
- If any name turns out to be taken, stop and report. Do not pick an alternative name without the owner.
- After each step, report one line: done, or what failed.

---

## Step 1: Check prerequisites

Run and report versions:

```bash
git --version
python3 --version        # need 3.10 or newer
node -v && npm -v        # need Node 20 or newer
gh --version             # GitHub CLI
```

If `gh` is missing, install it (`brew install gh` on macOS, or the official instructions for the OS). If Node is missing, tell the owner to install it from nodejs.org.

## Step 2: Confirm the names are free

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://pypi.org/pypi/jevbrief/json
npm view jevbrief name 2>&1 | head -1
gh repo view parthkomalwad/jevbrief 2>&1 | head -1
```

Expected: PyPI returns `404`, npm reports not found (`E404`), GitHub reports the repo cannot be found. If any name exists, stop and report.

## Step 3: Log in to GitHub (HUMAN)

Ask the owner to run:

```bash
gh auth login
```

Choose GitHub.com, HTTPS, and log in with the browser. Continue once `gh auth status` shows the account `parthkomalwad`.

## Step 4: Create the repository

```bash
cd /c/Parth/jevbrief    # repo root; already contains docs/
git init -b main
```

Create these files.

`README.md`:

```markdown
# jevbrief
> Clean, traceable state briefings for TypeSafe's Jev model.

jevbrief turns messy sources like web pages into small, clean state for Jev, drops the noise with deterministic rules, and records exactly what was kept, what was dropped, and why.

**Status:** under active development. v0.1.0 (Python, web page adapter, trace viewer) ships Thursday, September 24, 2026.

Community project, not affiliated with TypeSafe AI.
```

`LICENSE`: standard MIT license text, copyright 2026 Parth Komalwad.

`.gitignore`: Python and Node defaults, plus `.env`, `.env.*` (except `.env.example`), `dist/`, `build/`, `*.egg-info/`, `.venv/`, `node_modules/`, `traces/`, `*.jsonl`.

The build spec and this runbook live in `docs/` (`docs/jevbrief-spec.md`, `docs/jevbrief-setup-runbook.md`). Keep them there.

Then publish the repo:

```bash
git add .
git commit -m "Initial commit: README, license, docs"
gh repo create parthkomalwad/jevbrief --public --source . --push \
  --description "Clean, traceable state briefings for TypeSafe's Jev model"
gh repo edit parthkomalwad/jevbrief --add-topic jev,typesafe,ai-agents,llm,python,playwright
```

## Step 5: Claim the name on PyPI

### 5a. Create a token (HUMAN)

Ask the owner to:

1. Go to pypi.org → Account settings → confirm two-factor authentication is on.
2. API tokens → Add API token → scope "Entire account" → copy it.
3. Run `export PYPI_TOKEN=...` in the terminal Claude Code is using.

### 5b. Build and upload the placeholder

Create the placeholder in a separate folder so it never mixes with the real package:

```bash
mkdir -p /c/Parth/jevbrief-pypi-placeholder/jevbrief && cd /c/Parth/jevbrief-pypi-placeholder
```

`jevbrief/__init__.py`:

```python
__version__ = "0.0.1"
```

`pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "jevbrief"
version = "0.0.1"
description = "Clean, traceable state briefings for TypeSafe's Jev model. Early placeholder, v0.1.0 coming soon."
readme = "README.md"
requires-python = ">=3.10"
license = "MIT"
authors = [{ name = "Parth Komalwad" }]

[project.urls]
Homepage = "https://github.com/parthkomalwad/jevbrief"
```

Copy the repo's `README.md` into this folder, then:

```bash
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash; use .venv/bin/activate on macOS/Linux
pip install build twine
python -m build
TWINE_USERNAME=__token__ TWINE_PASSWORD="$PYPI_TOKEN" twine upload dist/*
```

Verify: `curl -s -o /dev/null -w "%{http_code}\n" https://pypi.org/pypi/jevbrief/json` returns `200`.

### 5c. Swap the token (HUMAN)

Ask the owner to delete the account-wide token on PyPI and create a new one scoped only to the `jevbrief` project, stored for tonight's v0.1.0 release. Then run `unset PYPI_TOKEN`.

## Step 6: Claim the name on npm

### 6a. Log in (HUMAN)

Ask the owner to confirm npm two-factor authentication is on, then run:

```bash
npm login
```

Continue once `npm whoami` prints the owner's username.

### 6b. Publish the placeholder

```bash
mkdir -p /c/Parth/jevbrief-npm-placeholder && cd /c/Parth/jevbrief-npm-placeholder
```

`package.json`:

```json
{
  "name": "jevbrief",
  "version": "0.0.1",
  "description": "Clean, traceable state briefings for TypeSafe's Jev model. TypeScript version coming soon.",
  "license": "MIT",
  "author": "Parth Komalwad",
  "repository": "github:parthkomalwad/jevbrief",
  "keywords": ["jev", "typesafe", "ai-agents", "llm"]
}
```

`README.md`:

```markdown
# jevbrief
Clean, traceable state briefings for TypeSafe's Jev model. The Python version is at https://pypi.org/project/jevbrief. The TypeScript version is coming soon.
```

```bash
npm publish --access public
```

npm may ask the owner for a 2FA code (HUMAN). Verify with `npm view jevbrief version`, which should print `0.0.1`.

## Step 7: Record the claims in the repo

Back in the repo root (`/c/Parth/jevbrief`), add this to the bottom of `README.md`:

```markdown
## Packages
- Python: https://pypi.org/project/jevbrief (placeholder until v0.1.0)
- npm: https://www.npmjs.com/package/jevbrief (placeholder, TypeScript version planned)
```

```bash
git commit -am "Link claimed package names"
git push
```

## Step 8: Hand off to the build

Report a final summary with the three links: GitHub repo, PyPI page, npm page.

Then open `docs/jevbrief-spec.md` and begin its "Build order and checkpoints" section at step 1, working inside the repo root (`/c/Parth/jevbrief`). The real package in this repo will replace the PyPI placeholder when v0.1.0 is published tonight. Use the same package name `jevbrief` and version `0.1.0`.

---

## Launch posts for X (for the owner, not Claude Code)

**Post now (building in public):**

> Building jevbrief: an open-source SDK that turns messy web pages (and later games, logs, robots) into clean, small state for @typesafeai's Jev.
>
> The twist: every fact it drops gets a reason code, so you can see what Jev was told, what it wasn't, and why.
>
> Shipping v0.1 tonight. github.com/parthkomalwad/jevbrief

**Post at launch (tonight):**

> jevbrief v0.1 is live.
>
> Same Jev, same tasks. Raw page state: [X]% correct, [N] tokens. jevbrief: [Y]% correct, [M] tokens.
>
> Other tools show what Jev decided. jevbrief shows what Jev was told, what it wasn't told, and why.
>
> pip install jevbrief
> [video] [repo link]

Fill in the bracketed numbers from the real benchmark results. Do not post estimated numbers.

Setup complete when all three links resolve and Claude Code has started step 1 of the build spec.
