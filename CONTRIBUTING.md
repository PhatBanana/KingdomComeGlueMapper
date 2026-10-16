# Contributing

KingdomComeGlueMapper is developed on Windows and converts assets from your own
installed copies of KCD1 and KCD2. **No game archives, extracted assets or
generated packages are accepted in a pull request.**

## Set up a development environment

The converter is a plain set of Python modules in [tools](tools) with no
package metadata and no build step. Python 3.13 and 3.14 were verified on
Windows x64; the pinned native dependency decides which of them can install:

| Python | `pip install -r requirements-setup.txt` | Test suite |
|---|---|---|
| 3.13 | installs every pinned dependency | green |
| 3.14 | **fails**, leaving the environment empty | green, but only if you supply the dependencies yourself |

On **Python 3.14** `xatlas==0.0.11` publishes no cp314 wheel, so pip builds it
from source and needs a C++ toolchain. Without the Visual Studio C++ Build Tools
the command aborts with `Failed building wheel for xatlas`. The failure is
atomic: nothing else from the requirements file is installed, not even NumPy or
Pillow. `requirements-test.txt` pins xatlas too, so it fails the same way.
`xatlas` is required to build the release EXE, so 3.13 is the straightforward
choice for a development environment.

Use 3.13 if you want the documented commands to work without a compiler:

```powershell
git clone https://github.com/SamG-Coder/KingdomComeGlueMapper.git
cd KingdomComeGlueMapper
py -3.13 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-setup.txt
.venv/Scripts/python.exe tools/setup_app.py
```

For the test suite:

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-test.txt
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

`requirements-test.txt` adds Lupa (executable Lua checks) and xatlas on top of
`requirements-npc-effects.txt` and `requirements-lighting.txt`. You do not need
the games, the Modding Tools, or any asset to run the suite.

## Before opening a pull request

Run the checks the CI workflow in
[validate.yml](.github/workflows/validate.yml) runs. The workflow also
invokes `--help` on a fixed list of command-line entry points; the last command
here stands in for that sweep:

```powershell
.venv/Scripts/python.exe -m compileall -q tools
.venv/Scripts/python.exe -m unittest discover -s tests -v
.venv/Scripts/python.exe tools/compare_packages.py --help
```

The following deviations are expected on a machine with no game assets and
report as skips, not failures: missing CUDA/OptiX DLLs, and the game-asset
room-rental fixtures.

A focused run is much faster while iterating:

```powershell
.venv/Scripts/python.exe -m unittest tests.test_brush_registration -v
```

When an optional native backend is genuinely absent, skip the test instead of
letting it error, so that a missing extra cannot be mistaken for a regression:

```python
try:
    import optional_backend
except ImportError:
    self.skipTest('optional backend not installed')
```

## Tests

Every conversion rule that can be checked without the games belongs in
[tests](tests). The suite builds synthetic archives and meshes in memory, so
a test must never require a game installation, and it must not write into
`outputs/` or `research/`. Follow the existing style: one `unittest` module per
converter, imports taken from `tools/`.

## Reporting an issue

Include, as far as you can:

- converter commit, release or setup version
- game version and which game the asset came from
- the in-game location, or coordinates
- whether the problem is appearance, collision, interaction or persistence
- reproduction steps and a screenshot
- relevant `setup.log` excerpts, or a report file from `outputs/`

Do not attach game archives or extracted game content.

## Pull requests

Keep a pull request to one concern. Say what you changed, why, and how you
verified it. If a change cannot be verified without the games, state that
plainly rather than implying a runtime fix; the maintainer validates appearance
and gameplay in retail. Mention the exact commands you ran and their result.

Documentation-only and test-only pull requests are welcome.
