# Third-party licenses

Date: 2026-11-17 (system time). Scope: the 94 packages pinned in [../requirements.lock](../requirements.lock), which is what a locked install gets.

**This is an engineering inventory, not legal advice.** It records what each package *declares* in its own metadata. It does not replace reading the license texts, and nobody here has checked patents, trademarks or the licenses of anything a package downloads at run time.

## What was checked

- Every distribution in the project's virtual environment was read through `importlib.metadata`: the `License-Expression` field, then the `License` field, then the `License ::` classifiers.
- A scan for `GPL`, `AGPL`, `SSPL`, `BUSL`, `Commons Clause`, `proprietary`, `elastic`, `unknown`, and for packages declaring nothing found **no match**. The only package with nothing declared is this project itself.
- For the packages below that need a closer look, the license files actually shipped inside the installed wheel were listed.
- The lock was installed with `--require-hashes` into a clean environment; `pip check` reported no conflicts and all tests passed.

## What was not checked

- Whether a declared license is *true*. Metadata is written by the package author. A wrong or missing declaration would not show up here.
- License files for most packages (only the ones listed below were opened).
- Packages that are pulled in only when a feature is used at run time (LiteLLM can load provider SDKs or other optional components on demand).
- This project's own license: **not decided yet** (see INDEX.md). Until it is, nothing here may be taken as permission to redistribute this repository.

## Declared licenses, grouped

| Declared | Count | Notes |
| --- | --- | --- |
| MIT (`MIT`, `MIT License`) | 40 | permissive |
| BSD-3-Clause / BSD License | 19 | permissive |
| Apache-2.0 / Apache Software License | 19 | permissive; some Apache packages carry a NOTICE file that must be kept on redistribution |
| BSD-2-Clause | 2 | Pygments, xxhash |
| PSF-2.0 / Python Software Foundation License | 2 | typing_extensions, aiohappyeyeballs |
| Dual or compound (`Apache-2.0 OR MIT`, `Apache-2.0 OR BSD-2-Clause`, `Apache-2.0 AND MIT`, `MIT AND PSF-2.0`, `Apache-2.0 AND CNRI-Python`, `BSD License / Apache Software License`, `MIT License / Apache Software License`) | 7 | ormsgpack, packaging, aiohttp, greenlet, regex, python-dateutil, sniffio |
| **MPL-2.0 (alone or in a compound)** | **3** | **certifi, tqdm, orjson (see below)** |
| `MIT License, Apache License, Version 2.0` | 1 | sqlite-vec (see below) |

That is 93 packages, the ones installed on Windows. The 94th locked package, `httpx2-jsfetch` 1.0 (declared `BSD-3-Clause`, pure Python), is only installed on Emscripten (Python in a browser) and was not installed or opened here.

The counts come from grouping the declared strings, so a package whose string is spelled differently lands in a different row. They are an approximation; the lock file is the exact list.

## Packages that need attention

### MPL-2.0 (weak, file-level copyleft)

| Package | Version | Declared | License files in the wheel |
| --- | --- | --- | --- |
| certifi | 2026.10.23 | MPL-2.0 | `LICENSE` (it also bundles a modified `ca-bundle.crt`) |
| tqdm | 4.70.1 | `MPL-2.0 AND MIT` | `LICENCE` |
| orjson | 3.13.0 | `MPL-2.0 AND (Apache-2.0 OR MIT)` | `LICENSE-APACHE`, `LICENSE-MIT`, `LICENSE-MPL-2.0` |

Using these as unmodified dependencies is the ordinary case and does not put MPL terms on this project's own code. What MPL asks for is that if *those files* are modified and distributed, the modified files stay under MPL with source available, and the license notice is kept. **This project modifies none of them.**

### sqlite-vec 0.1.9 (native binary)

- Declared: `MIT License, Apache License, Version 2.0`.
- Ships a native library, `sqlite_vec/vec0.dll`.
- **No license file is shipped inside the wheel**, so the declaration could not be checked against a text here.
- It is not used directly: it is a dependency of `langgraph-checkpoint-sqlite`. The workflow engine does not call it.
- Open question for whoever redistributes this: whether to keep it. It could be avoided by implementing a small checkpoint saver, at the cost of maintaining that code.

### tokenizers 0.23.3

- The `License` field is empty; the classifier says Apache Software License.
- **No license file is shipped inside the wheel.**

### regex 2026.11.15

- Declared `Apache-2.0 AND CNRI-Python`. Both are permissive; the CNRI text must be kept with redistributions. A license file is shipped.

### aiohttp 3.14.5, greenlet 3.5.6

- Compound declarations (`Apache-2.0 AND MIT`, `MIT AND PSF-2.0`). Permissive. Not opened.

## Tools used during development (not in the lock)

| Tool | Version | Declared | Used for |
| --- | --- | --- | --- |
| uv | 0.13.8 | `MIT OR Apache-2.0` | generating the lock, in a throwaway environment |
| Playwright for Python | 1.65.2 | Apache-2.0 | the browser smoke test (optional extra `browser`; it is in the lock because the lock was compiled with that extra) |
| Microsoft Edge | 156.0.4314.58 (read from the running browser in an earlier session) | proprietary, already installed on the machine | driven by Playwright; nothing is downloaded or redistributed |

## Relationship to PrintLab

PrintLab is licensed PolyForm Noncommercial 1.0.0 and is a **separate program** this project calls through its command line and its HTTP interface. No PrintLab source or documentation is copied into this repository. PrintLab's license applies to PrintLab; whether anything about using it alongside this project is restricted for a given use is a question for its license text, not for this file.

## Reference project

The design of this project was informed by reading NarraFork (MPL-2.0) documentation and source. **No NarraFork code was copied.** If any file were ever copied from it, that file would have to stay under MPL-2.0 with its notice.

## How to refresh this

```bash
# regenerate the lock (in a throwaway environment that has uv)
uv pip compile pyproject.toml --extra test --extra browser --universal --generate-hashes --python-version 3.11 --output-file requirements.lock
# verify it installs on its own
python -m venv /tmp/check && /tmp/check/Scripts/python -m pip install --require-hashes -r requirements.lock && /tmp/check/Scripts/python -m pip install --no-deps -e . && /tmp/check/Scripts/python -m pytest -q
```

Re-read this file after a refresh: new packages, changed declarations, and anything that newly declares MPL/GPL-family terms or ships a binary need a human look.
