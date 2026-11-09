# Hardening backlog

Recorded 2026-11-07 after the 0.4.16 release. This is a proposal and reference;
`tools/soak.py` and the process-tree tests are the first implemented pieces.

**Status 2026-11-09 (0.5.1, public):** actions 1–3 are done. Action 1 is
`tools/soak.py`, which measures repeated discovery/status cycles (`make soak`)
and Qt window create/close cycles (`make soak-qt`), reporting RSS, file
descriptors, threads, and tracemalloc.

- CLI, 300 cycles: RSS +0.01 MB, 0 descriptors, 0 threads, tracemalloc +24 KB
  (it plateaus, so the early growth was cache, not a leak).
- Qt, 100 cycles: RSS +0.05 MB, 0 descriptors, 0 threads, tracemalloc +62 KB.
  Every window was collected (`weakref` and `shiboken6.isValid`) and the widget
  count returned to baseline after each cycle.
- Falsifiability: a planted 64 KiB-per-cycle allocation fails the metrics, and
  a held Qt window fails the window-survival check.

Action 2 hardens the process layer: `run_git()` now kills and reaps the group
when `communicate()` raises, `_terminate_process_group()` escalates from
SIGTERM to SIGKILL without masking the original error, and tests cover both.
One gap is accepted and documented: a process that `git` forked can outlive a
SIGKILL of repopull. Timeout and cancellation kill the whole group.

Action 3 audits Qt lifetime. Worker signals auto-disconnect when the window is
destroyed, so a finished task cannot retain it; close-while-running cancels the
task and quits only after it reports; windows and tasks are collectable in the
tests. The only parentless widget is the pre-window "already running" warning.

## Language decision: Python first; no Rust wrappers

**Conclusion:** keep the orchestration, state handling, and GUI in Python. Do not
wrap the Python code in a "safe Rust" layer.

Reasons:

- Python already prevents the ordinary memory-corruption class in Python code:
  no buffer overflows, use-after-free, double-free, or pointer arithmetic.
- A Rust wrapper around Python is normally a Python extension: Python still runs
  in CPython, and the boundary uses unsafe FFI. `#![forbid(unsafe_code)]` in our
  crate would not cover PyO3, CPython's C API, or PySide6's Qt/C++ layer.
- Rust does not prevent leaks (`Rc` cycles, `Box::leak`, forgotten resources),
  deadlocks, TOCTOU races, orphaned processes, command injection, or Qt lifetime
  bugs. It prevents undefined behavior in safe Rust, not all resource bugs.
- PySide6 is the largest native surface. Wrapping the Python layer does nothing
  for Qt's C++ code.

Rust becomes reasonable only for a **small, self-contained native component**
with a narrow API and a measured need, such as a process supervisor/cgroup
killer or a strict parser for untrusted binary input. Prefer a separate helper
binary over a Python extension when fault isolation is the goal. Do not start a
Rust rewrite without evidence that it fixes a specific observed failure class.

## What Python covers, and what it does not

| Risk | Python's position |
|---|---|
| Buffer overflow, use-after-free, double-free | Handled for Python objects by CPython; native extensions are outside that guarantee. |
| Ordinary object leaks | Reference counting plus cycle GC, but long-lived references, signals, caches, and Qt parents can still retain objects. |
| Data races | The GIL does not make compound operations atomic or protect filesystem check-then-act. |
| Deadlocks | Not prevented; locks and worker handoffs still need design and tests. |
| Runaway processes | OS-level problem; timeouts, process groups, cgroups, and signal handling are required. |
| Qt lifetime bugs | Python wrappers do not protect against deleted C++ objects or signal connections that retain windows. |

## Top 5 proposed actions

1. **Add a resource soak harness.** Run hundreds of discovery/check/repair cycles
   and measure RSS, open file descriptors, thread count, and `tracemalloc`
   growth. Add a repeated Qt window create/close test with `weakref` and
   `shiboken6.isValid()` checks. Done when a leak produces a failing report.
   **Done 2026-11-09:** `tools/soak.py`, `make soak`, and `make soak-qt`.
   CLI and Qt baselines were flat; planted allocation and window leaks both
   fail the run.

2. **Test and harden process-tree termination.** Add a fake `git` that forks a
   sleeping child; verify timeout, cancellation, and parent-SIGKILL behavior.
   Audit `run_git()` so any exception from `communicate()` still kills and reaps
   the child. Done when no descendant survives the tested paths, or the residual
   parent-SIGKILL gap is explicitly accepted and documented. **Done 2026-11-09
   (one accepted gap):** timeout, cancellation, and parent-SIGKILL of `git`
   itself are tested; `communicate()` exceptions now kill and reap the group;
   SIGTERM escalation is tested. A forked descendant surviving a parent SIGKILL
   is documented by an expected-failure test and accepted, because `pdeathsig`
   applies to `git`, not its children.

3. **Audit Qt lifetime and signal ownership.** Check long-lived signal
   connections, parentless widgets, worker callbacks, and close-while-running
   behavior. Add a quit/cancel stress test and ensure windows and tasks are
   collectable. Done when repeated open/close leaves no retained windows.
   **Done 2026-11-09:** `make soak-qt` covers repeated create/close; GUI tests
   cover close-while-running, task collectability, and signal ownership.

4. **Add race and TOCTOU fault injection.** Deterministically test mount changes
   between scan and state write, state-file changes during repair, cancellation
   during `git`, and simultaneous state writers. Done when each scenario has a
   failing test or a documented last-writer-wins policy.

5. **Add low-cost CI guardrails and keep the Rust decision gated.** Run tests
   with `-X dev -W error` and `faulthandler`; add dependency/security checks for
   the packaging environment; keep Python/PySide6 updated. Done when CI catches
   resource/lifecycle regressions and the packaging update policy is written
   down.

## Existing strengths (audited at 0.4.16)

- `git.py`: timeouts, `start_new_session=True`, process-group SIGTERM/SIGKILL,
  scrubbed `GIT_*` environment, disabled hooks/fsmonitor, and
  `setpriv --pdeathsig` when available.
- `runtime.py`: one-run `flock` guard.
- `rootstate.py`: atomic, unique-temp state writes; malformed state refused.
- GUI workers: discovery and root-state checks run off the UI thread and return
  immutable results through Qt signals.

## Known gaps

- A SIGKILL of repopull can still leave children forked by `git`; `pdeathsig`
  kills `git`, not necessarily its descendants. Accepted and covered by an
  expected-failure test.
- `list`/GUI state writes are atomic but not all serialized by the run lock.

For the full documentation index, see [README.md](../README.md#documentation-index).
