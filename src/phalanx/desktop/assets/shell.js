/* The privileged page contains package code only. Result documents are sandboxed. */
(() => {
  "use strict";
  const byId = id => document.getElementById(id);
  const files = { targets: null, openSelection: null, calcSelection: null, history: null };
  let api = null;
  let generation = 0;
  let busy = false;
  let closing = false;
  let activeJob = null;
  let resultJob = null;
  let pollTimer = null;
  let pollFailed = false;
  let room = null;
  let disposeResolve = null;
  let preferences = { sfxVolume: 22, musicVolume: 16, reduceMotion: false };
  let settingsWrite = Promise.resolve();
  const notice = message => { byId("notice").textContent = message || ""; byId("notice").hidden = !message; };
  const status = message => { byId("operation-status").textContent = message; };
  const sendRoom = message => { if (room && room.contentWindow) room.contentWindow.postMessage(message, "*"); };
  const controls = () => {
    const blocked = !api || busy || closing;
    for (const id of ["pick-targets", "pick-open-selection", "pick-calc-selection", "pick-history"]) byId(id).disabled = blocked;
    byId("open-result").disabled = blocked || !files.targets;
    byId("calculate").disabled = blocked || !files.calcSelection || !files.history;
    byId("clear-open-selection").disabled = blocked || !files.openSelection;
    byId("save-result").disabled = blocked || !resultJob;
    byId("show-inputs").disabled = !api || closing;
    byId("retry-status").hidden = !pollFailed;
    byId("retry-status").disabled = !api || closing || !activeJob || !pollFailed;
    byId("open-form").setAttribute("aria-busy", String(busy));
    byId("calculate-form").setAttribute("aria-busy", String(busy));
  };
  const setInputs = visible => {
    byId("inputs").hidden = !visible;
    byId("show-inputs").setAttribute("aria-expanded", String(visible));
  };
  const disposeRoom = async () => {
    if (!room) return;
    const previous = room;
    // Dispose AudioContext and pending starts before tearing down all DOM listeners.
    // The iframe removal is also the hard lifetime boundary if acknowledgement fails.
    await new Promise(resolve => {
      let timeout;
      const done = () => { clearTimeout(timeout); disposeResolve = null; resolve(); };
      disposeResolve = done;
      timeout = setTimeout(done, 250);
      sendRoom({ type: "phalanx-desktop-dispose" });
    });
    previous.remove();
    if (room === previous) room = null;
  };
  const showResult = async (response, request) => {
    if (closing || request !== generation) return;
    await disposeRoom();
    if (closing || request !== generation) return;
    room = document.createElement("iframe");
    room.title = "위험자산 편성실 · 목표비중 결과";
    // No same-origin, popup, navigation, form, or download capability is granted.
    room.setAttribute("sandbox", "allow-scripts");
    room.srcdoc = response.html;
    byId("room-host").replaceChildren(room);
    byId("room-host").hidden = false;
    byId("welcome").hidden = true;
    resultJob = { job_id: response.job_id, generation: request };
    byId("save-status").textContent = response.saved_path ? `저장됨 · ${response.saved_path}` : response.mode === "saved" ? "저장 파일 조회 중 · 복사본 저장 가능" : "결과 보존 중 · 아직 저장하지 않음";
    setInputs(false);
  };
  const matches = (response, request, job) => !closing && request === generation && response.generation === request && (!job || response.job_id === job);
  const accept = async (response, request, job = null) => {
    if (!matches(response, request, job)) return;
    pollFailed = false;
    if (!response.ok || response.state === "error") {
      busy = false;
      activeJob = null;
      status("처리하지 못했습니다. 입력을 확인한 뒤 다시 실행할 수 있습니다.");
      notice(response.error || "처리 중 오류가 발생했습니다.");
      controls();
      return;
    }
    status(response.stage || "처리 중");
    activeJob = response.job_id;
    if (response.state === "complete") {
      if (typeof response.html === "string") await showResult(response, request);
      if (request !== generation || closing) return;
      busy = false;
      activeJob = null;
      status(`${response.stage || "처리 완료"} · 결과 상태: ${response.status || "확인 필요"}`);
      controls();
      return;
    }
    pollTimer = setTimeout(() => queryJob(response.job_id, request), 300);
  };
  const fail = (error, request, job = null) => {
    if (closing || request !== generation || (job && job !== activeJob)) return;
    if (job) {
      // A transport error says nothing about the worker. Keep its identity and
      // lock new submissions until a status query confirms its final state.
      pollFailed = true;
      status("연결 오류 · 기존 작업을 보존했습니다. 작업 상태를 다시 확인해 주세요.");
    } else {
      busy = false;
      activeJob = null;
      status("연결 오류 · 처리 상태를 확인하지 못했습니다.");
    }
    notice(String(error && error.message || error));
    controls();
  };
  const queryJob = async (job, request) => {
    if (closing || request !== generation || activeJob !== job) return;
    pollFailed = false;
    controls(); notice(""); status("기존 작업 상태를 확인하고 있습니다.");
    try { await accept(await api.job_status(job, request), request, job); }
    catch (error) { fail(error, request, job); }
  };
  byId("retry-status").addEventListener("click", () => {
    if (!api || closing || !pollFailed || !activeJob) return;
    queryJob(activeJob, generation);
  });
  const pick = async (kind, key, label) => {
    if (!api || busy || closing) return;
    busy = true; controls(); notice("");
    try {
      const response = await api.choose_file(kind);
      if (closing) return;
      if (response.ok === false) notice(response.error);
      else if (!response.cancelled && response.token) {
        files[key] = response.token;
        byId(label).textContent = response.name;
        byId(label).title = response.name;
      }
    } catch (error) { notice(String(error)); }
    finally { busy = false; controls(); }
  };
  byId("pick-targets").addEventListener("click", () => pick("targets", "targets", "targets-name"));
  byId("pick-open-selection").addEventListener("click", () => pick("selection", "openSelection", "open-selection-name"));
  byId("pick-calc-selection").addEventListener("click", () => pick("selection", "calcSelection", "calc-selection-name"));
  byId("pick-history").addEventListener("click", () => pick("history", "history", "history-name"));
  byId("clear-open-selection").addEventListener("click", () => {
    files.openSelection = null; byId("open-selection-name").textContent = "이름 미확인으로 열기"; controls();
  });
  const begin = async mode => {
    if (!api || busy || closing) return;
    if (mode === "open" ? !files.targets : !files.calcSelection || !files.history) return;
    busy = true;
    const request = ++generation;
    clearTimeout(pollTimer);
    pollFailed = false;
    resultJob = null;
    byId("save-status").textContent = "새 결과를 처리하고 있습니다.";
    controls(); notice(""); status(mode === "open" ? "저장 결과 검증 중" : "선정 입력을 고정하고 계산을 시작합니다.");
    await disposeRoom();
    if (closing || request !== generation) return;
    byId("room-host").hidden = true;
    byId("welcome").hidden = false;
    try {
      const response = mode === "open" ? await api.open_result(files.targets, files.openSelection, request) : await api.calculate(files.calcSelection, files.history, request);
      await accept(response, request);
    } catch (error) { fail(error, request); }
  };
  byId("open-form").addEventListener("submit", event => { event.preventDefault(); begin("open"); });
  byId("calculate-form").addEventListener("submit", event => { event.preventDefault(); begin("calculate"); });
  byId("show-inputs").addEventListener("click", () => setInputs(byId("inputs").hidden));
  byId("save-result").addEventListener("click", async () => {
    if (!api || busy || closing || !resultJob) return;
    busy = true; controls(); notice("");
    const saved = { ...resultJob };
    try {
      const response = await api.save_result(saved.job_id, saved.generation);
      if (!matches(response, saved.generation, saved.job_id)) return;
      if (response.cancelled) return;
      if (!response.ok) { notice(response.error || "저장하지 못했습니다. 결과는 화면에 보존되어 있습니다."); byId("save-status").textContent = "저장 실패 · 결과 보존 중"; }
      else byId("save-status").textContent = `저장 완료 · ${response.saved_path}`;
    } catch (error) { notice(String(error)); byId("save-status").textContent = "저장 실패 · 결과 보존 중"; }
    finally { busy = false; controls(); }
  });
  window.addEventListener("message", event => {
    if (!room || event.source !== room.contentWindow || !event.data || typeof event.data !== "object") return;
    if (event.data.type === "phalanx-room-disposed") { if (disposeResolve) disposeResolve(); return; }
    if (closing) return;
    if (event.data.type === "phalanx-room-ready") { sendRoom({ type: "phalanx-desktop-settings", preferences }); return; }
    if (event.data.type !== "phalanx-room-preferences" || !api) return;
    const value = event.data.preferences;
    if (!value || !Number.isInteger(value.sfxVolume) || !Number.isInteger(value.musicVolume) || typeof value.reduceMotion !== "boolean" || value.sfxVolume < 0 || value.sfxVolume > 100 || value.musicVolume < 0 || value.musicVolume > 100) return;
    preferences = { sfxVolume: value.sfxVolume, musicVolume: value.musicVolume, reduceMotion: value.reduceMotion };
    const next = { ...preferences };
    // Preserve order if a slider produces several writes while the filesystem is busy.
    settingsWrite = settingsWrite.then(async () => {
      if (closing) return;
      const response = await api.save_preferences(next);
      if (!response.ok) notice(response.error || "설정을 저장하지 못했습니다.");
    }).catch(error => notice(String(error)));
  });
  const silence = () => sendRoom({ type: "phalanx-desktop-silence" });
  const closePending = () => {
    if (closing) return;
    closing = true; clearTimeout(pollTimer); silence(); controls();
    status("실행 중인 작업을 마친 뒤 창을 닫습니다. 강제 취소하지 않습니다.");
  };
  window.PhalanxDesktopLifecycle = Object.freeze({ silence, closePending });
  document.addEventListener("visibilitychange", () => { if (document.hidden) silence(); });
  window.addEventListener("pagehide", () => { closing = true; clearTimeout(pollTimer); sendRoom({ type: "phalanx-desktop-dispose" }); });
  let initialized = false;
  const initialize = async () => {
    if (initialized || closing || !window.pywebview || !window.pywebview.api) return;
    initialized = true; api = window.pywebview.api;
    try {
      const response = await api.bootstrap();
      if (closing) return;
      if (!response.ok) { api = null; notice(response.error); status("초기화 실패 · 앱을 닫고 환경을 확인해 주세요."); return; }
      preferences = response.preferences;
      notice(response.notice);
      status("준비 완료 · 저장 결과를 열거나 새 목표비중을 계산하세요.");
    } catch (error) { api = null; notice(String(error)); status("초기화 실패"); }
    finally { controls(); }
  };
  window.addEventListener("pywebviewready", initialize, { once: true });
  initialize();
})();
