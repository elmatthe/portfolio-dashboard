# Global Developer Preferences
 
This file defines my general workflow, preferences, and patterns across all projects.
Read this at the start of every session and apply these defaults unless a project-level
`CLAUDE.md` (or equivalent) or a dropped markdown instruction file overrides them.
 
---
 
## My Machines & Workspace Roots
 
I work across more than one machine. Use the roots and constraints for whichever machine
the current session is running on. Paths and permissions differ between them, so never
assume a path from one machine exists on another — confirm against the matching block below.
 
The `claude-skills-main` folder listed per machine is my local clone of reusable skills;
it sits alongside the workspace roots, not inside a single project.
 
### CSPW-PC — Work Computer
 
**Workspace roots:**
```
C:\Users\ematthew\Desktop\Files\Coding_Repositories
C:\Users\ematthew\Desktop\Files\Coding_Repositories\MyProjects\CSPW-PC
C:\Users\ematthew\Desktop\Files\claude-skills-main
```
 
**Specs relevant to building:**
- OS: Windows 11 Pro (64-bit)
- CPU: AMD Ryzen 5 PRO 7545U — 6 cores / 12 threads
- RAM: 32 GB
- GPU: AMD Radeon 740M (integrated) — no discrete GPU / CUDA
- Storage: 256 GB SSD (limited free space — keep builds and downloads lean)
**Permissions — locked down (this is the important one):**
- User `EMatthew` is a **Standard User with no admin rights.**
- Cannot run `.exe`/`.msi` installers that write to `C:\Program Files` or the registry —
  that requires an IT password I do not have.
- Can run local PowerShell scripts (execution policy: `RemoteSigned`).
- **Workaround / default approach:** use portable app versions (standalone `.exe` or `.zip`)
  that run from `C:\Users\ematthew\`, browser extensions, and fully self-contained,
  in-repo setups. Nothing should require a system-wide install on this machine. This is the
  machine the "contain everything in the repo and venv" rules in Setup and Launch Files
  matter most for.
### HOME-PC — Personal Computer
 
**Workspace roots:**
```
C:\Users\ematthew\Desktop\Apps\Coding\Repository_Workspaces
C:\Users\ematthew\Desktop\Apps\Coding\Repository_Workspaces\MyProjects\Home-PC
C:\Users\ematthew\Desktop\Apps\Coding\claude-skills-main
```
 
**Specs relevant to building:**
- OS: Windows 11 Pro (64-bit)
- CPU: AMD Ryzen 7 9800X3D — 8 cores / 16 threads
- RAM: 32 GB
- GPU: NVIDIA GeForce RTX 5070 (CUDA available) + AMD Radeon integrated
- Storage: 2 TB SSD (ample free space)
**Permissions — full access:**
- User `ematthew` is an **Administrator (full access).**
- Can run any `.exe`/`.msi` installer, modify the registry, and write to `C:\Program Files`
  (right-click → "Run as Administrator" for elevated tasks).
- Can run local PowerShell scripts (execution policy: `RemoteSigned`).
- A discrete CUDA-capable GPU is available here, so GPU-accelerated work (ML, CUDA, heavier
  local models) is viable on this machine but not on CSPW-PC.
### MacBook Pro — Personal Laptop (details to be added)
 
I sometimes work on a MacBook Pro. Specs, workspace roots, and permissions will be filled
in here later. Until then, treat any macOS session as undefined for paths — ask me for the
workspace root and machine details before assuming anything.
 
**Workspace roots:**
```
(to be added)
```
 
**Specs relevant to building:**
- (to be added)
**Permissions:**
- (to be added)
---
 
## How I Work With You
 
I use a two-surface workflow:
 
- **AI chat tool (e.g. Claude.ai, ChatGPT, Gemini)** is my planning and thinking layer. I use it to design features, interpret output, write implementation markdowns, and make architectural decisions.
- **AI coding agent / CLI / editor agent (e.g. Claude Code, Codex, Cursor)**
  is my execution layer. It receives those plans as markdown files and implements them.
Instruction markdown files I drop into a repo are **temporary**. Once the plan is fully implemented and verified, remove the instruction file. Do not treat them as permanent project documentation.
 
If I drop a markdown plan into a repo root, read it fully before doing anything. Do not begin implementation until you have internalized the full scope. If anything in the plan is ambiguous, ask before starting — do not assume and proceed.
 
---
 
## Project Structure I Typically Use
 
This is my default preference, not a rigid rule. Follow project-level instructions if they differ. When starting a new project or reorganizing an existing one, default to this layout unless told otherwise.
 
```
/ProjectName/                <- repo root, keep this clean and minimal
  README.md
  CLAUDE.md                  <- blank template pointing to AI-WORKSPACE.md
  CODEX.md                   <- blank template pointing to AI-WORKSPACE.md
  CURSOR.md                  <- blank template pointing to AI-WORKSPACE.md
  AI-WORKSPACE.md            <- This File
  setup_and_run.bat          <- Windows launcher and setup for non-technical users
  setup_and_run.command      <- macOS launcher and setup for non-technical users
  /.claude/                  <- Claude agent config
    /skills/                 <- reusable capability documents (see Skills section)
  /.codex/                   <- Codex agent config
    /skills/                 <- reusable capability documents (see Skills section)
  /scripts/                  <- all Python and automation scripts go here
  /md-instructions/          <- markdown files for instructions and documentation
    CHANGELOG.md             <- persistent, updated every version/bugfix
    Briefing.md              <- project overview for AI context, kept current
    Instructions_Template.md <- instructions file for describing intent and plan (will often drop in root /ProjectName/)
  /files/                    <- all other assets and supporting files go here
  /test-files/               <- sample/input files for the AI agent to test features against
  /tests/                    <- pytest tests (created as tools are built; run by verify)
  /test-logs/                <- gitignored; manual logs for the final release pass only
```
 
For cross-platform projects, the structure forks at the root:
 
```
/ProjectName/
  README.md
  CLAUDE.md                 <- blank template pointing to AI-WORKSPACE.md
  CODEX.md                  <- blank template pointing to AI-WORKSPACE.md
  CURSOR.md                 <- blank template pointing to AI-WORKSPACE.md
  AI-WORKSPACE.md           <- This File
  Instructions_Template.md  <- instructions file dropped in the main root /ProjectName/ for cross-platform projects
  setup_and_run.bat
  setup_and_run.command
  /.claude/
    /skills/                <- reusable capability documents, shared across both platforms
  /.codex/
    /skills/                <- reusable capability documents, shared across both platforms
  /test-files/              <- sample/input files for the AI agent to test features against
  /Windows/
    /scripts/
    /md-instructions/
      CHANGELOG.md
      Briefing.md
    /files/
    /tests/                 <- pytest tests for this platform (run by verify)
    /test-logs/             <- gitignored; manual logs for the final release pass only
  /MacOS/
    /scripts/
    /md-instructions/
      CHANGELOG.md
      Briefing.md
    /files/
    /tests/                 <- pytest tests for this platform (run by verify)
    /test-logs/             <- gitignored; manual logs for the final release pass only
```
 
The repo root should stay minimal. Non-technical users will download and unzip this —
they should only ever see the README and the setup launchers at the top level.
 
---
 
## The `/md-instructions` Folder
 
Two files in this folder are **permanent and must be maintained throughout the project**:
 
**`CHANGELOG.md`** — Log every version, feature addition, bug fix, and breaking change.
Update this after completing each phase or meaningful change. Use clear version markers.
 
**`Briefing.md`** — A living project overview written so that a new AI chat session
can read it and immediately understand the full project without me having to re-explain
everything. Keep this current. It should cover: what the project does, the tech stack,
architecture decisions, known issues, current version, and what has been built so far.
 
All other markdown files in `/md-instructions` are temporary instruction drops.
Remove them once implemented.
 
**Cross-platform projects:** `Briefing.md` and `CHANGELOG.md` are maintained per platform
(in `/Windows/md-instructions/` and `/MacOS/md-instructions/`), since they track the state
of each platform's build. Instruction and plan markdowns are **not** split this way — drop
them in the main repo root (`/ProjectName/`). A single instruction file specifies the work
for both platforms, so there is no need to maintain or read a separate copy under each OS.
 
---
 
## The `.claude/skills` and `.codex/skills` Folders
 
Skills are **reusable capability documents**. A skill captures a repeatable, durable
pattern the agent can load on demand — how to generate an Excel workbook a certain way,
how to write VBA macros to my conventions, how to scaffold a tkinter launcher, how to
run a particular build/package step. I found that pulling this kind of knowledge into
skills (instead of re-explaining it every session) dramatically improved consistency,
cut down on repeated prompting, and saved tokens across sessions.
 
Skills live under the relevant agent's config folder, with one folder per agent:
 
- **`.claude/skills/`** — skills for Claude / Claude Code.
- **`.codex/skills/`** — skills for Codex.
Both folders follow the same conventions described here. When a skill applies to whichever
agent is running, use it. When you create a new skill, place it under the config folder for
the agent you are (Claude → `.claude/skills/`, Codex → `.codex/skills/`); if the capability
is genuinely agent-agnostic and useful to both, it is fine to mirror it into both folders.
 
Each skill lives in its own folder with a `SKILL.md` describing the capability:
 
```
/.claude/skills/            (or /.codex/skills/)
  excel-generation/
    SKILL.md
  vba-macros/
    SKILL.md
```
 
**Skills vs. instruction markdowns — the key distinction:**
 
- **`/md-instructions` (temporary)** — a *one-time plan* for a specific feature or phase
  in *this* project. Read it, implement it, delete it. It describes *what to build right now*.
- **`.claude/skills` and `.codex/skills` (reusable)** — a *durable capability* that recurs
  across phases and across projects. It is not deleted when a task finishes. It describes
  *how to do a kind of thing well, every time*.
Rule of thumb: if I would have to explain the same thing again next session or in the
next project, it belongs in a skill. If it is only relevant to the task in front of us
right now, it belongs in `/md-instructions`.
 
**Using and creating skills:**
 
- During planning for any non-trivial build, identify the skills the work will likely need.
- Check your skills folder (`.claude/skills/` for Claude, `.codex/skills/` for Codex) for
  an existing skill that fits before writing fresh instructions or solving from scratch.
- Use an existing skill when one applies — do not reinvent a pattern I have already captured.
- When a reusable capability is missing and the pattern is likely to recur, create a new
  skill for it rather than burying the knowledge in a throwaway instruction file.
- When relevant, list the expected skills in the build plan so I can see them up front.
---
 
## The `/files` Folder
 
The `/files` folder is the catch-all for everything that is not a script or a markdown
instruction. This keeps the repo root and `/scripts/` clean. Everything that does not
have a more specific home goes here, including:
 
- Assets (images, icons, cover art, sample files)
- Config files and templates
- `__pycache__/` and any other auto-generated Python folders
- Test data and fixtures
- Output folders (e.g. converted files, exports)
- Any other supporting files the scripts depend on
Add `/files/__pycache__/` and any auto-generated subfolders within `/files/` to
`.gitignore` as appropriate.
 
---
 
## The `/test-files` Folder
 
`/test-files` sits at the repo root and holds **sample or input files I drop in for the AI
coding agent to test features against** — for example a sample PDF for a converter, a
spreadsheet for a parser, or an audio clip for an ffmpeg tool. When verifying a feature,
look here first for something to run against, and feel free to use whatever is present.
 
This folder is for **test inputs only**. It is not part of the shipped product — non-technical
end users never see it. Do not confuse it with `/files` (assets the program actually depends
on at runtime) or `/test-logs` (the QA log output). If a test file is large or sensitive,
consider gitignoring it rather than committing it.
 
---
 
## Setup and Launch Files
 
`setup_and_run.bat` (Windows) and `setup_and_run.command` (macOS) serve two purposes:
 
1. **First-time setup** — sets up the project environment, keeping everything inside the
   repo and its `.venv` where possible (pip dependencies into the venv, self-contained tools
   like ffmpeg into the repo), and only installing onto the PC itself (e.g. Python) when
   there is no contained alternative.
2. **Daily launcher** — the user double-clicks this every time they want to run the program.
Assume the end user is **non-technical**. They should never need to open a terminal,
navigate folders, or install anything manually. The setup script handles everything,
guiding the user through any one-time installs with simple prompts.
 
**Contain everything in the repo and venv first.** Unless a project specifically says
otherwise, setup should keep as much as possible *inside the project folder* — pip
dependencies into the project's `.venv`, and self-contained tools (like a static `ffmpeg`
binary) downloaded into the repo (e.g. `files/bin/`) and added to PATH for that session
only. The goal is that running the program touches the actual PC as little as possible.
This matters most on locked-down work machines where the user has no admin access: a
fully self-contained setup just works, with nothing installed system-wide.
 
**Only install onto the PC when there is genuinely no alternative.** The main unavoidable
exception is **Python itself** — a virtual environment cannot be created without an
interpreter already present, so if Python is completely missing it must be installed onto
the machine. That is the *only* point where a real system install, and the admin/user
choice below, should come up. If Python already exists, the user is never prompted about
scope at all. For anything that *can* live in the repo (ffmpeg and similar), prefer the
in-repo copy and never escalate to a system-wide install unless the contained approach
genuinely cannot be done.
 
**Guided install prompts (Y/N).** For the big, one-time installs only — Python, or a tool
being set up because the contained route failed — the script should pause and ask the user
to confirm with a simple Y/N before installing. Do *not* prompt for small things like
individual pip packages; those install silently into the venv. Setting up a self-contained
tool inside the repo gets a single plain-language Y/N too, framed clearly as "this stays in
the project folder, nothing is installed on your PC." Keep every prompt readable for a
non-technical user, and add a short line near the top of the script explaining that setup
keeps things in the project folder and will only ask before installing something onto the
PC if it is truly required.
 
**Install scope — only when a system install is forced.** Many work computers do not allow
admin access. *When, and only when,* something must be installed onto the PC itself (in
practice: a missing Python), the script must let the user choose where it goes:
 
- **Just for me (user scope)** — installs only for the current user and needs **no admin
  rights**. This is the safe default, especially on locked-down work machines.
- **For all users (machine scope)** — installs system-wide and **requires admin rights**.
Do not ask this question at all unless a system install is actually required. When it is,
ask once. On Windows, drive the install through `winget` using `--scope user` or
`--scope machine` to honour the choice. On macOS, user scope installs via Homebrew (no
admin password needed); system-wide Python uses the official python.org installer. Whatever
the choice, the install should land somewhere the user is actually allowed to write to.
 
**Security-software blocking (unavoidable first-run prompt).** When these files are
downloaded from the internet, Windows SmartScreen / Defender / WatchGuard (and the macOS
Gatekeeper equivalent) will often block the *first* run because the file is unsigned. No
code inside the script can suppress this — only the user clicking through can. So the
script should include a short, friendly note up front explaining exactly what to click:
on Windows, "More info" then "Run anyway"; on macOS, System Settings > Privacy & Security >
"Open Anyway". Make clear this is normal and only happens once.
 
On macOS, the launcher must be a **`.command`** file (not `.sh`) so it opens cleanly on a
double-click from Finder, and it must have execute permissions (`chmod +x`). On Windows, the
`.bat` should keep the command prompt window open during setup and launch so the user can
see a live log of what is happening. Once the process completes, prompt the user to press
Enter to close the window. Do not leave it open permanently with no way to dismiss it.
 
---
 
## Python and Script Preferences
 
- Python is the primary language for most scripts, but use whatever language or tool that will get the job done most effectively. If another language, runtime, or tool is clearly a better fit for a specific task, use it — just briefly explain why. Do not force Python when something else is obviously better.
- GUIs should use `tkinter` unless a project specifies otherwise.
- The main entry point for multi-tool projects is a `launcher.py` — a clean GUI window
  that presents each available tool as a button or menu item.
- Suppress unnecessary console/command prompt popups when launched from the setup file.
  Users should only see the GUI, not terminal output.
- Organize scripts logically inside `/scripts/`. If there are many, use subfolders.
- Keep scripts modular — each tool is its own file, called from the launcher.
---
 
## Research Before Building
 
Before writing any new code for a feature or task, search GitHub for existing repos,
scripts, or libraries that already solve the problem. The goal is to do less work by
borrowing well-tested, working code rather than building from scratch.
 
Before that GitHub search, check your skills folder first (`.claude/skills/` for Claude,
`.codex/skills/` for Codex). If I have already captured a
skill that covers the capability, use it — that is the fastest path and the most
consistent result. Only move on to searching GitHub when no existing skill applies.
 
When researching:
 
- Search GitHub for repos that handle the specific task (e.g. "ffmpeg python wrapper",
  "m4b chapter maker", "tkinter file converter gui")
- Look for repos with recent commits, a reasonable star count, and an open license
  (MIT, Apache 2.0, or similar permissive licenses are fine to borrow from)
- Read through the relevant files to confirm they actually work and are clean enough
  to integrate — do not pull in bloated or unmaintained code
- Prefer borrowing a self-contained script or module over pulling in an entire framework
When you find something useful:
 
- Add the files directly into the appropriate folder in the current repo
  (usually `/scripts/` or a subfolder within it)
- Note in the commit message and `CHANGELOG.md` where the code came from
- Only take what is needed — do not copy entire repos wholesale if only one file is relevant
- If the borrowed code needs minor modifications to fit the project, make them cleanly
  and comment what was changed and why
If nothing useful is found after a reasonable search, proceed to write it from scratch
and say so. Do not spend excessive time searching when the task is simple enough to
implement directly.
 
---
 
## Implementation Approach
 
When given a plan (via a dropped markdown or direct instruction):
 
1. **Read everything first.** Understand the full scope before writing a single line of code.
2. **Identify and check skills.** For any non-trivial build, work out which reusable
   capabilities the task needs and check your skills folder (`.claude/skills/` for Claude,
   `.codex/skills/` for Codex) for existing ones. Use them
   where they apply. If a needed capability is missing and likely to recur, plan to
   create a skill for it. Note the expected skills in the plan.
3. **Research before building.** If there are existing libraries, GitHub repos, or tools
   that solve part of the problem, find and evaluate them before writing from scratch.
4. **Phase your work.** Break implementation into clear phases. After each phase, verify it
   mechanically — add or update the `pytest` test(s) for what you built and run `verify`
   (see Testing and Verification) — before moving on. Do not chain multiple phases together
   without checkpointing.
5. **Prefer working code over clever code.** These projects are used by non-technical users.
   Reliability matters more than elegance.
6. **Do not refactor unrelated code** unless a bug hunt phase is explicitly instructed or
   the plan calls for it. Stay in scope.
7. **If unsure, stop and ask.** Do not guess on ambiguous requirements and proceed —
   especially when it involves file structure, user-facing behaviour, or data handling.
---
 
## Testing and Verification
 
Correctness should be **mechanical, not aspirational**. Prefer automated checks that run on
every setup — and a single `verify` gate — over hand-written test logs. Automated tests
catch regressions for free, every run, forever; manual logs only catch what someone
remembers to look at, and they burn tokens. The order of preference is:
 
1. **Automated `pytest` tests** — the default for verifying anything.
2. **The `verify` step** — one command that gates a change as "done".
3. **A manual test log** — reserved only for the heavy final release pass (see below).
### Automated tests (`pytest`) — the default
 
Every tool should have at least one small test that asserts its core function returns the
right thing for a known input. Start tiny — one test per tool is enough to begin — and grow
coverage as bugs are found (each fixed bug gets a test so it cannot come back).
 
- Tests live in a `tests/` folder inside the relevant platform directory (or the repo root
  for single-platform projects), e.g. `tests/test_<tool>.py`.
- Use the files in `/test-files` as known inputs. A test feeds a fixture from `/test-files`
  to a tool and asserts the expected result — this is exactly what that folder is for.
- Keep tests fast and deterministic: real known inputs, exact expected outputs, no network
  calls or reliance on machine-specific state.
- Add `pytest` to `requirements.txt` (pinned, like everything else).
When you add or change a tool, add or update its test in the same phase — not as an
afterthought. "It works" means "there is a test proving it works."
 
### The `verify` step — the gate
 
A change is not "done" until it passes a single verification command. `verify` runs the
fast, mechanical checks that turn the written rules in this document into an actual gate.
At minimum it should:
 
- **Run the test suite** (`pytest`) and fail if any test fails.
- **Check that all dependencies are pinned** in `requirements.txt` (no unpinned packages).
- **Check that `CHANGELOG.md` was updated** for the current change (e.g. its top version is
  ahead of the last committed one, or matches the version in `Briefing.md`).
If any check fails, `verify` fails and the work is not done. Run `verify` before committing
a completed phase and before any release. Treat a failing `verify` the way you would a
failing build: stop and fix it, do not work around it.
 
(When a `verify` script does not yet exist in a project, run the equivalent checks by hand —
run `pytest`, scan `requirements.txt` for unpinned lines, confirm the CHANGELOG was
bumped — and note that a `verify` script should be added.)
 
### Manual test log — final release pass only
 
The detailed manual checklist below is **token-heavy** and is reserved for the **final
release verification of a major plan** — not individual features, routine fixes, or
mid-session checkpoints. Use it only when:
 
- A full multi-phase plan is complete and ready for release verification, or
- Building and packaging an exe or installer for distribution.
For everything smaller, automated tests plus `verify` are the check — do not write a log.
 
Manual logs live in the `/test-logs` folder inside the relevant platform directory
(e.g. `/Windows/test-logs` or `/MacOS/test-logs`). This folder is gitignored — it is a
working folder, not part of the shipped product. Do not delete it between sessions. Name
each pass by version and purpose, e.g. `v1.2.0_pre-release.md`.
 
When a manual log is warranted, use this structure:
 
```markdown
# [Project Name] — [Test Type] — v[X.X.X]
Date: YYYY-MM-DD
Tester: [AI agent or person who ran this pass]
 
## Summary
Brief description of what this release pass is checking and why.
 
## [Section — e.g. Launcher, GUI, Script Name]
 
- [ ] Description of the check -> Expected outcome
- [x] Description of the check -> Expected outcome  PASSED
- [~] Description of the check -> FAILED: short description of what went wrong
 
## Issues Found
 
| # | Severity | File | Description | Status |
|---|----------|------|-------------|--------|
| 1 | Critical  | launcher.py | Crash on first run when no config exists | Fixed |
| 2 | Minor     | gui/main.py | Window title shows placeholder text | Open |
```
 
Status markers: `- [ ]` not yet checked, `- [x]` passed, `- [~]` failed (describe inline),
`- [-]` skipped (explain why).
 
### Severity Levels
 
When logging issues found (in a release pass or a bug hunt):
 
- **Critical** — breaks core functionality or crashes for a non-technical user
- **Minor** — cosmetic, edge case, or unlikely to affect typical use
- **Suggestion** — optional improvement, not a bug
Fix all criticals before the pass is closed, and add a `pytest` test for each one so it
cannot regress. Flag minors and suggestions for my review before touching them.
 
---
 
## Bug Hunt Phase
 
Most multi-phase plans include a final bug hunt. When you reach it:
 
- Go through each script systematically, not just the ones you touched.
- Flag deprecated library usage, missing error handling, hardcoded paths, and
  anything that would break for a non-technical user on a fresh machine.
- Report issues by severity: **Critical** (breaks core function), **Minor** (cosmetic or
  edge case), **Suggestion** (optional improvement).
- Fix criticals immediately. Flag minors and suggestions for my review before touching them.
- For each bug you fix, add a `pytest` test that reproduces it, so it cannot regress.
- Run `verify` (or the equivalent checks) at the end of the bug hunt before calling it done.
---
 
## Session and Context Management
 
At natural breakpoints where context from the current session is no longer needed for
what comes next, remind me of my options and let me choose. Never do this automatically.
 
The right moment to suggest this is after a self-contained phase is fully complete and
verified — meaning the work is committed, tested, and the next phase does not depend on
anything currently in context. Do not suggest it mid-implementation, mid-debug, or any
time you still need the current context to continue correctly.
 
When the moment is right, offer these options clearly:
 
- **Start a new session** — best when the next phase is a clean start with no dependency
  on current context (e.g. moving to a completely different part of the project)
- **Clear context** — wipes the context window entirely; use when the slate needs to be
  clean but you are staying in the same working directory. In Claude Code this is `/clear`;
  other tools may have an equivalent or you can simply start a fresh session.
- **Compact / summarize context** — summarizes the conversation into a compressed context;
  use when some history is still useful but the window is getting long. In Claude Code
  this is `/compact`; other tools may have an equivalent.
Word the reminder something like:
 
> "Phase X is complete and committed. Before we move on, you may want to start a fresh
> session or clear/compact the context to keep things efficient. What would you like to do?"
 
Do not phrase it as a recommendation for one option over another unless the situation
clearly favours one. Always let me decide.
 
---
 
## Git and Version Habits
 
- Commit after each completed phase, not just at the end.
- Write clear commit messages that describe what changed and why.
- Work on a branch for anything non-trivial. Do not push directly to main.
- If I have not specified a branch, ask before committing.
---
 
## Dependency and Environment Rules
 
**`requirements.txt` location:** Always place `requirements.txt` inside `/scripts/`,
not in the repo root. The setup file knows to look there.
 
**Pin all dependencies:** When writing or updating `requirements.txt`, always pin every
package to an exact version (e.g. `requests==2.31.0`, not just `requests`). Never leave
a dependency unpinned. If adding a new package, check the current latest stable version
and pin to that. Without a pinned version, anyone who installs it later might get a newer
version that broke something — for example, `openpyxl` has changed behaviour between
versions in ways that silently break existing code. This applies to test/dev tools too:
`pytest` (and anything else `verify` relies on) goes in `requirements.txt`, pinned like
the rest.
 
**`.gitignore` hygiene:** Before every commit, verify that the following are in
`.gitignore` if they exist in the project:
 
```
.venv/
.python_runtime/
__pycache__/
*.pyc
*.pyo
dist/
build/
*.spec
```
 
These folders are auto-generated and machine-specific — they are large, they rebuild
themselves automatically on each machine, and they should never be in the repo. They
sometimes do not get added to `.gitignore` and end up pushed to GitHub by mistake. If
`.gitignore` is missing entirely, create it before the first commit.
 
**Binary dependencies (ffmpeg, etc.):** The `setup_and_run` file is responsible for making
required binaries available without the user doing anything manually beyond approving a
simple Y/N prompt (see Setup and Launch Files). By default, set these up **inside the repo**
— download a self-contained build into something like `files/bin/` and add it to PATH for
the session — so nothing is installed onto the PC and no admin rights are needed. A system
ffmpeg that already exists may simply be used. Only fall back to a system-wide install (and
the "just me" vs "all users" choice) if the contained approach genuinely cannot be done, and
always provide a "No, I'll do it manually" fallback with the exact download URL. The program
should never crash or show a raw error because a binary is missing — check for required
binaries at startup and handle absence gracefully with a clear prompt.
 
If a binary is bundled into the repo (e.g. `files/bin/ffmpeg`), make sure its folder is
gitignored if you do not intend to commit the binary itself.
 
---
 
## Session Kickoff Routine
 
At the start of every new session on an existing project, before doing anything else,
read these files in order:
 
1. `CLAUDE.md` or `AI-WORKSPACE.md` (repo root, if present) — the global instruction file
2. `md-instructions/Briefing.md`
3. `md-instructions/CHANGELOG.md`
Then confirm: the current version, what was last worked on, and any open issues flagged
in the changelog. If any of these files are missing or appear out of date, flag it before
proceeding. If a dropped instruction markdown is present in the repo root, read that next.
 
Also take note of what is available in your skills folder (`.claude/skills/` for Claude,
`.codex/skills/` for Codex) so you know which reusable
capabilities you can draw on this session. You do not need to read every skill in full
up front — just know what exists, and load the relevant `SKILL.md` when a task calls for it.
 
If you are a CLI-based coding agent, output this confirmation as a brief summary at the
start of your first response. If you are a chat-based AI, state it conversationally.
 
---
 
## What I Don't Want (unless specifically instructed in another instructions prompt to do otherwise)
 
- Do not add dependencies or libraries without briefly explaining what they are and why
  they are needed. You have full discretion to choose the best library for the job —
  I trust your judgment on what will get the task done most effectively. Just do not add things silently without a one-line explanation.
- Do not restructure folders that are not part of the current task.
- Do not leave debug print statements or test files in the final output.
- Do not assume a task is complete until its tests pass and `verify` (or the equivalent checks) is green. "Looks done" is not done.
- Do not produce output that requires the user to manually edit a config file or
  run a terminal command to finish setup — the setup script should handle everything.