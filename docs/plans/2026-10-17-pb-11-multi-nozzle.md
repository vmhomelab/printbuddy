# PB-11 Multi-Nozzle Printer Support Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Complete generic downstream support for printers reporting more than two nozzles, including Snapmaker U1’s four independently reported toolheads.

**Architecture:** Existing Moonraker U1 telemetry already normalizes each toolhead into `nozzle`, `nozzle_2`, etc. Replace remaining dual-nozzle-only consumers with a shared interpretation of all numbered nozzle temperature keys. Keep Bambu dual-nozzle behavior unchanged while dynamically detecting the actual nozzle count for persisted printer metadata.

**Tech Stack:** Python/FastAPI, SQLAlchemy async sessions, pytest, Prometheus text exposition.

---

### Task 1: Define multi-nozzle temperature-key behavior

**Objective:** Add regression coverage proving all numbered nozzle temperature keys participate in status-change de-duplication and persisted nozzle-count detection.

**Files:**
- Create: `backend/tests/unit/test_status_broadcast_multi_nozzle.py`
- Modify: `backend/app/main.py`

**Step 1: Write failing test**

Create a four-nozzle fake printer state. Call `on_printer_status_change()` twice with only `nozzle_4` changed. Assert two WebSocket broadcasts. Mock the async database path and assert the printer’s `nozzle_count` becomes `4`.

**Step 2: Run test to verify failure**

Run: `uv run --directory backend pytest tests/unit/test_status_broadcast_multi_nozzle.py -q`
Expected: FAIL because the current status key only includes `nozzle` and `nozzle_2`, and auto-detection caps the persisted count at `2`.

**Step 3: Write minimal implementation**

Derive a deterministic tuple of all direct nozzle temperature keys (`nozzle`, `nozzle_2`, …), excluding target/heating auxiliary keys. Use it in the broadcast de-duplication key. Infer the highest reported nozzle index and persist that count once per printer.

**Step 4: Run test to verify pass**

Run: `uv run --directory backend pytest tests/unit/test_status_broadcast_multi_nozzle.py -q`
Expected: PASS.

### Task 2: Make multi-nozzle cooling and Prometheus metrics complete

**Objective:** Ensure safety checks and monitoring consume every reported nozzle, rather than only the first two.

**Files:**
- Modify: `backend/app/services/printer_manager.py`
- Modify: `backend/app/api/routes/metrics.py`
- Modify: `backend/tests/unit/services/test_printer_manager.py`
- Modify: `backend/tests/integration/test_metrics_api.py`

**Step 1: Write failing tests**

Add a cooldown test with a cool first and second nozzle but a hot fourth nozzle; it must wait rather than report safe. Add an authenticated metrics API test using a four-nozzle printer status; assert each current and target series uses labels `nozzle="0"` through `nozzle="3"`.

**Step 2: Run tests to verify failure**

Run: `uv run --directory backend pytest tests/unit/services/test_printer_manager.py tests/integration/test_metrics_api.py -q`
Expected: FAIL because the current consumers know only `nozzle_2`.

**Step 3: Write minimal implementation**

Collect direct nozzle-temperature keys dynamically in the manager cooldown guard and metrics route. Maintain numeric ordering and the existing 0-based Prometheus label convention. Emit targets only when their matching target temperature is present.

**Step 4: Run tests to verify pass**

Run: `uv run --directory backend pytest tests/unit/services/test_printer_manager.py tests/integration/test_metrics_api.py -q`
Expected: PASS.

### Task 3: Validate and publish safely

**Objective:** Verify the existing U1 adapter and UI remain compatible, then commit and publish the focused change on a dev-based feature branch.

**Files:**
- Review only: `backend/app/services/printer_providers/moonraker.py`
- Review only: `frontend/src/pages/PrintersPage.tsx`

**Step 1: Run focused tests**

Run: `uv run --directory backend pytest tests/unit/services/test_moonraker_provider.py tests/unit/services/test_printer_manager.py tests/unit/test_status_broadcast_multi_nozzle.py tests/integration/test_metrics_api.py -q`

**Step 2: Run style checks and backend suite**

Run: `uv run --directory backend ruff check app tests && uv run --directory backend ruff format --check app tests && uv run --directory backend pytest -q`

**Step 3: Build frontend**

Run: `npm run build` in `frontend/`.

**Step 4: Review and commit**

Run `git diff --check` and `git status --short`; stage only PB-11 source/tests/plan files; commit as `feat(printers): complete multi-nozzle support`; push `feat/pb-11-multi-nozzle` to origin.
