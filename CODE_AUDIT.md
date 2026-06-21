# Photobooth Code Audit

**Scope:** core `photobooth/` package, `photobooth_web/` Django app, docs & repo hygiene.
**Method:** full read of all 15 core modules (~3,570 LOC), the web app, and the three top-level docs (~1,840 LOC). No edits made.
**Date:** 2026-06-20

A headline first: the single most valuable finding is **not** in the code — it's that `ARCHITECTURE.md` documents a codebase that doesn't exist. This report leads with that, then code, then hygiene.

---

## Tier 1 — Documentation drift (fix first, low risk)

### 1.1 `ARCHITECTURE.md` describes a different program than the one in the repo

`ARCHITECTURE.md` presents a thermal/photo printer refactor as completed fact, but the code never adopted it — the current tree has zero `ThermalPrinter`. The doc is a survivor from an abandoned refactor branch (commits `b500eea` "v0.5.0-phase8 Documentation" and `5c91ea9` "pre-changes prior to phase 1 implementation") that documented the split before it was built. The split is still wanted as a future revision (real `PhotoPrinter` / Selphy CP1500 support), but it isn't in the code today.

Concretely, the doc documents:

| ARCHITECTURE.md says | Reality in code |
|---|---|
| `thermal_printer.py` / `ThermalPrinter` | `printer.py` / `Printer` |
| `photo_printer.py` / `PhotoPrinter` (CUPS/`lp`) | **does not exist** |
| `add_thermal_printer()`, `add_photo_printer()` | `add_printer()` only |
| `THERMAL_PRINTER_MAP`, `PHOTO_PRINTER_MAP` | `PRINTER_MAP` |
| `_do_thermal_print` / `_do_photo_print`, parallel printing | `_do_print` (receipt only) |
| Tests `test_thermal_printer.py`, `test_photo_printer.py`, `test_template_loader.py` | none exist; actual is `test_printer.py` |

Entire sections (Package Overview, Component Map, "Printers", the asyncio blocking-I/O table, and the "Running Tests" table) reference symbols and files that aren't there. `README.md` is *consistent* with reality (it calls PhotoPrinter "planned"), so the two docs contradict each other. This will actively mislead a future reader/contributor.

**Action:** Rewrite `ARCHITECTURE.md` to describe the current single `Printer` exclusively (`printer.py`, `add_printer`, `PRINTER_MAP`, `_do_print`) and regenerate the "Running Tests" table from the actual `tests/` directory (drop `test_thermal_printer.py`, `test_photo_printer.py`, `test_template_loader.py`; reflect `test_printer.py`). Capture the thermal/photo split as a scoped `BACKLOG.md` entry — "Thermal/photo printer separation + PhotoPrinter (CUPS/`lp`, Selphy CP1500)" — citing the abandoned-branch commits so the design isn't lost.

---

## Tier 2 — Code duplication (core package)

### 2.1 The "return to attract" block is copy-pasted ~6 times in `booth_main.py`
This pair —
```python
await self.display_url_with_context(ATTRACT_URL, **self._series_params())
attract = asyncio.create_task(self.panel.scroll(
    text="Press the big blue button to begin!  ", speed=0.005, count=999))
```
— appears at `booth_main.py:222`, `262`, `323`, `361`, `387`, `398`, and the literal string `"Press the big blue button to begin!  "` is repeated each time. The `run()` method is a 245-line monolith largely because of this.

**Proposal:** A helper `_return_to_attract() -> asyncio.Task` that flushes, navigates, and returns the new scroll task. Collapses ~5 blocks to one-liners and removes the string duplication. Tests like `test_series_flow.py` and `test_display_url_with_context.py` will validate the behavior is unchanged.

### 2.2 `_upload_or_enqueue` has two near-identical `except` arms
`booth_main.py:642-667` — the `TimeoutError` arm and the generic `Exception` arm do *exactly* the same thing (enqueue, set `pending_notice`, force a `net_www` re-probe) save for the log message.

**Proposal:** Catch `(asyncio.TimeoutError, Exception)` once, or factor the body into a nested `_handle_upload_failure(exc, key)`. `test_upload_offline_flow.py` covers this.

### 2.3 `run_local_cmd` is duplicated verbatim
Identical function in `booth.py:37` and `camera.py:37` (only the log level differs). **Proposal:** one home (it's a generic subprocess helper) and import it.

### 2.4 `_classify_error` doesn't classify
`booth_main.py:446` takes an exception and ignores it entirely — it branches only on the `hint` string and returns one of two constants. It's a two-line `if hint == "printer"` dressed up as a classifier. **Proposal:** inline it at the two call sites, or simplify to a dict lookup `{"printer": (...), "camera": (...)}[hint or "camera"]`.

---

## Tier 3 — Structure (`booth_main.py`, moderate restructure)

`booth_main.py` is 1,301 LOC and holds the 160-line module-constant header, the entire `PhotoBooth` class (run loop, startup, capture flows, review helpers, upload, printing), and `main()`. It's the natural target for the "moderate restructure" approved during scoping.

**Proposal — extract cohesive, already-grouped sections (the file even has `# ---` banners marking them):**
- **Receipt content** → the 35-line `_do_print` body (`:1236`) is pure presentation (marketing copy + QR). Move to a `receipt.py` / template so copy edits don't touch runtime logic.
- **Upload orchestration** → `_upload_or_enqueue` + `_upload_queue_worker` (`:580-754`) are a self-contained subsystem; could move to an `upload_flow` mixin/module.
- **Config constants** → the ~80 lines of `BOOTH_*` env constants (`:81-158`) into a small `config.py`, leaving `booth_main` to read behavior, not parse the environment.

This is extraction without redesign — public method names and the test surface stay put, so the existing suite is the regression check. Do 2.1–2.4 *first* (they shrink `run()` and make the boundaries obvious), then extract.

---

## Tier 4 — Web app duplication

### 4.1 Eight templates, one repeated skeleton
`single_final.html` and `last_capture.html` are nearly identical (same `frame/photo/overlay` structure + the same `reveal()` script; they differ only in the overlay PNG and the series banner). `series_final.html` is a third variant. Separately, `index.html`, `last.html`, `attract.html`, `series_capture.html`, `unavailable.html` all repeat the same `imgbox`/`center-fit` CSS boilerplate.

**Proposal:** A `base.html` with two blocks (the simple "centered image" layout and the "photo-behind-overlay + reveal-script" layout). `mainscreen/tests.py` and `test_series_overlay_views.py` validate the rendered output. Collapses ~8 files of duplicated `<style>`/JS to template inheritance.

### 4.2 Possibly-dead screen path
`last.html` (with `setTimeout("self.close()", 5000)`), the `last` view (`views.py:31`), the `last/` URL, and `Booth.display_last_shot()` (`booth.py:182`) appear to be a legacy path — the live flow uses `last_capture`, not `last`. Worth confirming and removing if dead (note `reset_last_shot` writes `last.jpg`, which *is* still used, so check carefully).

---

## Tier 5 — Latent bugs found along the way

Correctness issues, not just cleanups — flagged because the audit was meant to be thorough and the tests will catch regressions:

- **`Printer.__init__` kwargs loop is broken** — `printer.py:109`: `for k, v in kwargs:` iterates a **dict's keys** (strings), so unpacking `k, v` either throws or silently mangles. It only fires when callers pass `Usb` override kwargs (the booth doesn't today), so it's dormant — but it's wrong. Should be `for k, v in kwargs.items():` and `self.printer_spec` should be deep-copied (it currently mutates the shared `PRINTER_MAP` entry).
- **`probe_neopixel_available` constructs a real panel** — `neopixel.py:93` instantiates a second `Neopixel` on D18 every health re-probe. On hardware this re-inits the bus each `recheck_loop` tick for a degraded panel. Worth confirming that's intended vs. a lighter presence check.

---

## Tier 6 — Small cleanups (low-effort polish)

- **Typos baked into public names:** `DEAFULT_ORDER`, `DEAFULT_PIN` in `neopixel.py:31-32` (misspelled `DEFAULT`). Rename with a one-pass update.
- **Placeholder methods:** `Neopixel.flash()` and `cycle_text()` (`neopixel.py:329-335`) just delegate to `scroll` — dead stubs; remove or implement.
- **Commented-out dynamic `__getattr__`** in `printer.py:180-190` — delete.
- **`getIndex` / `valid_color_tuple`** — non-PEP8 naming amid otherwise black-formatted code; minor.

---

## Tier 7 — Repo hygiene (delete-only, zero risk)

- `=9.0.0` (empty file at repo root) — an accidental shell redirect from a `pip install >=9.0.0`. Delete.
- `test.py` at repo root — a 6-line AWS bucket-load scratch script, not a test. Remove or move to `references/`.
- `photobooth/build/` — a stale build tree mirroring source (`build/lib/photobooth/printer.py`, etc.). Delete and `.gitignore` it.
- `__pycache__` (7 dirs) and `ctp_utilities.egg-info` / `photobooth.egg-info` — gitignore.
- **`setup.py` and `pyproject.toml` conflict** — `setup.py` declares version `0.0.1`, author "Namachieli", BSD-3 classifier, and a *different* dependency list; `pyproject.toml` is the real one (v0.5.0). With a pyproject present, the stale `setup.py` is confusing and overrideable. Delete `setup.py`.

---

## Suggested sequencing

Each step is a commit on `v0.6.0`; run the suite after each.

1. **Hygiene deletes** (Tier 7) — instant, no behavior change.
2. **Doc reconciliation** (Tier 1.1) — rewrite `ARCHITECTURE.md` to current state; add the printer-split BACKLOG entry.
3. **Core dedup** (Tier 2) — `_return_to_attract`, unify upload except, dedupe `run_local_cmd`, simplify `_classify_error`.
4. **`booth_main.py` extraction** (Tier 3) — now that `run()` is smaller.
5. **Template inheritance** (Tier 4) + **bug fixes** (Tier 5) + **polish** (Tier 6).

Every code change above is covered by the existing suite (`tests/test_series_flow.py`, `test_upload_offline_flow.py`, `test_display_url_with_context.py`, `test_printer.py`, the Django `mainscreen` tests, etc.), so each step is independently validatable.

---

## Execution plan

Agreed approach: **batch the zero-risk work first**, get review, then move into the code tiers.

- **Pass 1 (done):** Tier 7 hygiene + Tier 1.1 `ARCHITECTURE.md` rewrite. Most Tier 7 targets (`=9.0.0`, `test.py`, `photobooth/build/`, the gitignore entries) were already gone; the only remaining item was the stale `setup.py`, now deleted. `ARCHITECTURE.md` rewritten to the current single `Printer`; the printer-split design was already captured in `BACKLOG.md`, whose closing doc-drift note was realigned. No behavior change — suite green (184 passed; the lone Django view test is skipped only because `django` isn't installed in this dev env).
- **Pass 2 (done):** Tier 2 core dedup — `_return_to_attract` helper (5 call sites + `ATTRACT_SCROLL_TEXT`), `_upload_or_enqueue` failure-tail factored into `_queue_for_retry`, `_classify_error` inlined + deleted, dead `run_local_cmd` removed from `booth.py`. `booth_main.py` −43 LOC net; suite green (184 passed); no reformatting of untouched lines.
- **Pass 3 (done):** Tier 3 `booth_main.py` extraction — three commits: `config.py` (constants + the two env-guard tests retargeted), `receipt.py` (receipt copy as a testable pure function), and `UploadFlowMixin` in `upload_flow.py` (the Phase 6 upload subsystem). `booth_main.py` 1,301 → 1,002 LOC. Suite green (184 passed) after each.
- **Pass 4 (done):** Tier 4/5/6, one commit per logical fix.
  - **Tier 4.1** — kiosk templates collapsed onto `base.html` + `base_centered.html` + `base_overlay.html`; 8 leaves now declare only their differences. Validated against 26 `mainscreen` tests + the series-overlay view tests.
  - **Tier 4.2** — the `last` screen path is **removed**: `last` view/URL/`last.html` + `Booth.display_last_shot` plus the legacy `examples/booth_init.py` (its only caller) and the two `mainscreen` `last` tests. `copy_to_last_shot`/`reset_last_shot`/`last.jpg` are kept (the review and final screens layer it); `index`/`/main/` is kept (it's the `probe_web_available` readiness endpoint).
  - **Tier 5.1** — `Printer.__init__` USB-kwarg override fixed (`kwargs.items()`, `getfullargspec(Usb).args`) and the shared-`PRINTER_MAP` mutation closed with a per-instance deep-copy; dead `self.inputs = locals()` removed; regression tests added.
  - **Tier 5.2** — `probe_neopixel_available` building a real panel is **intentional** (ws281x is write-only — constructability *is* the liveness check, transient discarded so the real panel starts clean). No change.
  - **Tier 6** — `DEAFULT_*` typos fixed; dead `flash()`/`cycle_text()` removed; commented-out `__getattr__` removed.

_Status: audit fully executed; `last`-path retirement done. One optional follow-up remains: a whole-tree `black .` sweep for pre-existing narrow-width formatting in `booth.py`/`camera.py`/`neopixel.py`/`test_env_example_consistency.py`._
