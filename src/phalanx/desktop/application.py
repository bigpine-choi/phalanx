"""Single-worker controller; immutable inputs, versioned replies and independent saves."""

from __future__ import annotations

import hashlib
import threading
import uuid
from collections.abc import Callable
from pathlib import Path

from phalanx.market_data.history.reader import HistoryReader
from phalanx.portfolio.allocation_input.service import AllocationInputService
from phalanx.portfolio.allocation_targets.service import AllocationTargetsService
from phalanx.portfolio.formation_room.parser import MAX_TARGETS_BYTES, parse_targets
from phalanx.portfolio.formation_room.selection import MAX_SELECTION_BYTES


def _read_input(path: Path, limit: int) -> bytes:
    from phalanx.desktop.storage import read_selected_file

    return read_selected_file(path, limit)


def _repository(path: Path) -> HistoryReader:
    from phalanx.market_data.history.windows_repository import WindowsHistoryRepository

    return WindowsHistoryRepository(path)


def _store(path: Path, payload: bytes) -> Path:
    from phalanx.desktop.storage import store_result

    return store_result(path, payload)


class DesktopApplication:
    """No GUI callbacks except a native close notification after the worker finishes.

    Every accepted request owns a monotonic generation and random job ID. There is
    one worker including input capture/open; snapshots are copies and save never
    changes calculation state. Public bridge authorization belongs to runtime.
    """

    def __init__(
        self,
        *,
        repository_factory: Callable[[Path], HistoryReader] = _repository,
        result_store: Callable[[Path, bytes], Path] = _store,
    ) -> None:
        self._repository_factory = repository_factory
        self._result_store = result_store
        self._lock = threading.RLock()
        self._generation = 0
        self._job_id = ""
        self._state: dict[str, object] = {"state": "idle", "stage": "준비"}
        self._payload: bytes | None = None
        self._worker: threading.Thread | None = None
        self._busy = False
        self._saving = False
        self._closing = False
        self._closed = False
        self._close_callback: Callable[[], object] | None = None

    def set_close_callback(self, callback: Callable[[], object]) -> None:
        with self._lock:
            self._close_callback = callback

    def _reply(self, **extra: object) -> dict[str, object]:
        # The calculation can publish its result just before the worker exits.
        # Keep polling clients in the running state until the worker clears _busy.
        state = self._state
        if self._busy and state.get("state") in {"complete", "error"}:
            state = {**state, "state": "running"}
        return {
            "ok": True,
            "generation": self._generation,
            "job_id": self._job_id,
            **state,
            **extra,
        }

    def _reject(self, message: str) -> dict[str, object]:
        return self._reply(ok=False, error=message)

    def _reject_start(self, message: str, generation: int) -> dict[str, object]:
        # A refused request never owns the existing job. Echo the caller's
        # generation so its UI can process the rejection without accepting a
        # stale job; expose the current worker identity separately for diagnosis.
        active_job = (
            {"generation": self._generation, "job_id": self._job_id}
            if self._busy or self._saving
            else None
        )
        return {
            "ok": False,
            "state": "rejected",
            "generation": generation,
            "job_id": None,
            "active_job": active_job,
            "error": message,
        }

    def _start(self, generation: int, action: Callable[[], None]) -> dict[str, object]:
        with self._lock:
            if self._closing or self._closed:
                return self._reject_start("종료를 기다리는 중입니다.", generation)
            if self._busy or self._saving:
                return self._reject_start("현재 작업이 끝난 후 다시 실행해 주세요.", generation)
            if type(generation) is not int or generation <= self._generation:
                return self._reject_start("이전 화면의 요청입니다.", generation)
            self._generation = generation
            self._job_id = uuid.uuid4().hex
            self._payload = None
            self._busy = True
            self._state = {"state": "running", "stage": "입력 파일 확인", "saved_path": None}
            self._worker = threading.Thread(
                target=self._run, args=(action,), name=f"phalanx-{self._job_id}", daemon=False
            )
            try:
                self._worker.start()
            except RuntimeError:
                self._worker = None
                self._busy = False
                self._state = {
                    "state": "error",
                    "stage": "작업 시작 실패",
                    "saved_path": None,
                    "error": "작업 스레드를 시작하지 못했습니다. 잠시 후 다시 시도해 주세요.",
                }
                return self._reply(ok=False)
            return self._reply()

    def _run(self, action: Callable[[], None]) -> None:
        try:
            action()
        except Exception:
            # Native paths and provider internals are never sent into a JS error.
            with self._lock:
                self._state = {
                    "state": "error",
                    "stage": "작업 실패",
                    "error": (
                        "입력 파일·DB 형식·선정 연결·접근 권한을 확인한 뒤 다시 시도해 주세요."
                    ),
                    "saved_path": None,
                }
        finally:
            with self._lock:
                self._busy = False
                callback = self._close_callback if self._closing and not self._closed else None
            if callback is not None:
                callback()

    def _complete(self, payload: bytes, selection: bytes | None, source: str, mode: str) -> None:
        from phalanx.desktop.view import render_result

        model = parse_targets(payload, source_name=source, selection_payload=selection)
        html = render_result(model, "calculated" if mode == "calculated" else "saved")
        with self._lock:
            if self._closed:
                return
            self._payload = payload
            self._state = {
                "state": "complete",
                "stage": model.status_label,
                "status": model.status,
                "html": html,
                "mode": mode,
                "saved_path": None,
                "save_state": "unsaved" if mode == "calculated" else "source",
                "targets_sha256": hashlib.sha256(payload).hexdigest(),
            }

    def open_result(
        self, targets_path: Path, selection_path: Path | None, generation: int
    ) -> dict[str, object]:
        def action() -> None:
            payload = _read_input(targets_path, MAX_TARGETS_BYTES)
            selection = _read_input(selection_path, MAX_SELECTION_BYTES) if selection_path else None
            self._complete(payload, selection, targets_path.name, "saved")

        return self._start(generation, action)

    def calculate(
        self, selection_path: Path, history_path: Path, generation: int
    ) -> dict[str, object]:
        def action() -> None:
            selection = _read_input(selection_path, MAX_SELECTION_BYTES)
            repository = self._repository_factory(history_path)
            with self._lock:
                self._state.update(
                    stage="저장 DB 검증 · 입력 준비 · 네 시나리오 계산 중",
                    selection_sha256=hashlib.sha256(selection).hexdigest(),
                    selection_name=selection_path.name,
                    history_name=history_path.name,
                )
            result = AllocationTargetsService(AllocationInputService(repository)).calculate_bytes(
                selection
            )
            self._complete(result.to_json_bytes(), selection, "이번 계산 결과.json", "calculated")

        return self._start(generation, action)

    def job_status(self, job_id: str, generation: int) -> dict[str, object]:
        with self._lock:
            if self._closed or job_id != self._job_id or generation != self._generation:
                return {"ok": False, "generation": generation, "job_id": job_id, "stale": True}
            return self._reply(closing=self._closing)

    def save_result(self, job_id: str, generation: int, output_path: Path) -> dict[str, object]:
        with self._lock:
            if job_id != self._job_id or generation != self._generation or self._closed:
                return {"ok": False, "generation": generation, "job_id": job_id, "stale": True}
            if self._payload is None or self._busy or self._saving or self._closing:
                return self._reject("저장할 결과가 없거나 다른 작업이 진행 중입니다.")
            self._saving = True
            payload = self._payload
        try:
            saved = self._result_store(output_path, payload)
            with self._lock:
                self._state.update(saved_path=str(saved), save_state="saved", save_error=None)
                return self._reply()
        except Exception:
            with self._lock:
                message = (
                    "저장하지 못했습니다. 기존 파일과 권한을 확인하고 새 경로로 재시도해 주세요."
                )
                self._state.update(save_state="error", save_error=message)
                return self._reply(ok=False, error=message)
        finally:
            with self._lock:
                self._saving = False
                callback = self._close_callback if self._closing and not self._closed else None
            if callback is not None:
                callback()

    def request_close(self) -> bool:
        """Return False to defer closing; never pretend the calculation is cancelled."""
        with self._lock:
            self._closing = True
            return not (self._busy or self._saving)

    def closed(self) -> None:
        with self._lock:
            self._closed = True
            self._closing = True
            self._close_callback = None
            worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join()
