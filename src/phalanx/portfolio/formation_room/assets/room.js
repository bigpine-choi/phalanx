/* Offline presentation only. Financial values are formatted by Python. */
(() => {
  "use strict";
  const data = JSON.parse(document.getElementById("room-data").textContent);
  const byId = (id) => document.getElementById(id);
  const put = (id, value, absent = "미산출") => {
    byId(id).textContent = value === null || value === undefined ? absent : String(value);
  };
  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = String(text);
    return element;
  };
  const desktopMode = document.body.dataset.desktopMode || "";
  const desktop = Boolean(desktopMode && window.parent !== window);
  if (desktop) {
    document.querySelector(".brand-caption").textContent = "편성실 · Windows";
    document.querySelector(".offline-label").textContent = desktopMode === "calculated" ? "이번 작업의 계산 결과" : "저장된 결과 조회";
    document.querySelector(".prototype-label").textContent = "Windows 편성실";
    byId("settings-storage").textContent = "음량·모션 설정만 사용자별 앱 데이터 폴더에 저장합니다. 투자 데이터는 포함하지 않습니다.";
  }
  const settingsKey = "phalanx.formation-room.preferences.v1";
  const preferences = { sfxVolume: 22, musicVolume: 16, reduceMotion: false };
  let storageAvailable = true;
  try {
    const stored = desktop ? null : JSON.parse(localStorage.getItem(settingsKey) || "null");
    if (stored && typeof stored === "object") {
      for (const key of ["sfxVolume", "musicVolume"]) {
        if (typeof stored[key] === "number" && Number.isFinite(stored[key])) {
          preferences[key] = Math.max(0, Math.min(100, stored[key]));
        }
      }
      if (typeof stored.reduceMotion === "boolean") preferences.reduceMotion = stored.reduceMotion;
    }
  } catch (_) { storageAvailable = false; }
  const showStorageNotice = () => {
    if (storageAvailable) return;
    byId("settings-storage").textContent = "이 환경에서는 설정 저장이 차단되어 있습니다. 현재 탭의 세션 설정으로 계속 동작합니다. 투자 데이터는 저장하지 않습니다.";
    byId("settings-storage").classList.add("unavailable");
  };
  const savePreferences = () => {
    if (desktop) {
      window.parent.postMessage({ type: "phalanx-room-preferences", preferences: { ...preferences } }, "*");
      return;
    }
    try {
      // Only these three presentation preferences are persisted. Never source data.
      localStorage.setItem(settingsKey, JSON.stringify(preferences));
    } catch (_) { storageAvailable = false; showStorageNotice(); }
  };
  showStorageNotice();
  // Probe blocked writes too; reads can succeed while storage is read-only.
  if (!desktop) savePreferences();
  const audio = window.PhalanxAudio.createController({
    sfxVolume: preferences.sfxVolume / 100,
    musicVolume: preferences.musicVolume / 100,
    onNotice: (message) => { byId("audio-notice").textContent = message; },
    onChange: (state) => {
      put("sound-state", state.starting ? "시작 대기 중" : state.enabled ? (state.musicPlaying ? "음악 켜짐" : "효과음 켜짐") : "무음");
      put("audio-status", !state.supported ? "이 브라우저는 Web Audio를 지원하지 않습니다." : state.starting ? "음향 시작 대기 중 · 시작 취소를 누르면 대기를 멈춥니다." : state.enabled ? (state.musicPlaying ? "효과음 · 배경음 재생 중" : "효과음 켜짐 · 음악 정지") : "무음 · 직접 켜기 전에는 재생되지 않습니다.");
      byId("audio-enable").disabled = state.enabled || state.starting || !state.supported;
      byId("audio-mute").disabled = !state.enabled && !state.starting;
      put("audio-mute", state.starting ? "시작 취소" : "전체 무음");
      byId("music-start").disabled = state.musicPlaying || state.starting || !state.supported;
      byId("music-stop").disabled = !state.musicPlaying && !state.starting;
      byId("audio-preview").disabled = state.starting || !state.supported;
    }
  });
  let disposed = false;
  const applyDesktopPreferences = value => {
    if (!value || !Number.isInteger(value.sfxVolume) || !Number.isInteger(value.musicVolume) || typeof value.reduceMotion !== "boolean") return;
    preferences.sfxVolume = Math.max(0, Math.min(100, value.sfxVolume));
    preferences.musicVolume = Math.max(0, Math.min(100, value.musicVolume));
    preferences.reduceMotion = value.reduceMotion;
    audio.setVolumes(preferences.sfxVolume / 100, preferences.musicVolume / 100);
    for (const [id, key] of [["sfx-volume", "sfxVolume"], ["music-volume", "musicVolume"]]) {
      byId(id).value = String(preferences[key]);
      put(`${id}-label`, `${preferences[key]}%`);
    }
    byId("reduce-motion").checked = preferences.reduceMotion;
    document.documentElement.classList.toggle("reduced-motion", preferences.reduceMotion);
  };
  const onDesktopMessage = event => {
    if (!desktop || event.source !== window.parent || !event.data || disposed) return;
    if (event.data.type === "phalanx-desktop-settings") applyDesktopPreferences(event.data.preferences);
    else if (event.data.type === "phalanx-desktop-silence") audio.silence();
    else if (event.data.type === "phalanx-desktop-dispose") {
      disposed = true;
      document.body.inert = true;
      audio.dispose();
      window.removeEventListener("message", onDesktopMessage);
      window.parent.postMessage({ type: "phalanx-room-disposed" }, "*");
    }
  };
  if (desktop) window.addEventListener("message", onDesktopMessage);
  let scenarioIndex = 0;
  let selectedCode = data.selected_codes[0] || null;
  const tabs = [];
  const current = () => data.scenarios[scenarioIndex];
  const announce = (message) => { put("live-status", message); };
  const symbols = new Map(data.symbols.map((symbol) => [symbol.code, symbol]));
  const assetColors = ["#78d2c3", "#7db2db", "#d5bc7e", "#a7b5dd", "#a6c39c", "#c49b9d", "#80beca", "#b0baa0"];
  const nameFor = (code) => {
    const symbol = symbols.get(code);
    return symbol && symbol.name_status === "verified_selection" && symbol.name ? symbol.name : "이름 미확인";
  };
  const colorFor = (code) => assetColors[data.selected_codes.indexOf(code) % assetColors.length];
  const identityFor = (code) => `${nameFor(code)} (${code})`;
  byId("demo-badge").hidden = !(data.presentation && data.presentation.synthetic_demo === true);

  put("source-name", data.source_name);
  put("overall-status", data.status_label);
  if (data.status !== "succeeded") byId("overall-status").classList.add(data.status === "partial" ? "warning" : "failure");
  put("calculation-date", data.calculation_date);
  put("selection-date", data.selection_as_of);
  put("selected-count", data.selected_count);
  put("observation-count", data.return_observation_count);
  put("success-count", data.succeeded_count);
  put("used-start", data.used_start);
  put("used-end", data.used_end);
  put("reference-price-date", data.reference_price_date);
  for (const scenario of data.scenarios) {
    byId("scenario-marks").append(node("span", scenario.status === "succeeded" ? "success" : ""));
  }
  const fingerprintRows = [{ label: "입력 파일 SHA-256 · 식별용", value: data.source_sha256 }, ...data.fingerprints];
  for (const item of fingerprintRows) {
    const row = node("div");
    row.append(node("dt", "", item.label), node("dd", "", item.value));
    byId("fingerprints").append(row);
  }
  for (const limitation of data.limitations) byId("limitations").append(node("li", "", limitation));

  const refreshReasons = () => {
    const list = byId("evidence-reasons");
    list.replaceChildren();
    for (const reason of data.reasons) list.append(node("li", "", `${reason.code}: ${reason.message}`));
    for (const scenario of data.scenarios) {
      if (scenario.failure) list.append(node("li", "", `${scenario.label} · ${scenario.failure.code}: ${scenario.failure.message}`));
    }
    if (!list.childElementCount) list.append(node("li", "", "준비·계산 실패 사유 없음. 저장된 네 시나리오 결과를 조회합니다."));
  };
  refreshReasons();

  const refreshDetail = () => {
    const scenario = current();
    const holding = scenario.holdings.find((item) => item.code === selectedCode);
    const symbol = symbols.get(selectedCode);
    const position = data.selected_codes.indexOf(selectedCode);
    const detail = byId("holding-detail");
    detail.dataset.code = selectedCode || "";
    detail.style.setProperty("--asset-color", selectedCode ? colorFor(selectedCode) : "transparent");
    put("detail-title", selectedCode ? nameFor(selectedCode) : "선정 종목 없음");
    put("detail-code", selectedCode, "—");
    put("detail-name-status", symbol && symbol.name_status === "verified_selection" ? "저장된 선정 자료에서 확인한 이름" : "이름 미확인 · 종목코드를 기준으로 구분합니다.");
    byId("detail-swatch").style.backgroundColor = selectedCode ? colorFor(selectedCode) : "transparent";
    put("detail-number", position >= 0 ? String(position + 1).padStart(2, "0") : "—");
    put("detail-weight", holding ? holding.weight_display : null);
    put("detail-risk", holding ? holding.relative_risk_display : null);
    put("detail-bounds", holding ? `${holding.lower_display} / ${holding.upper_display}` : null);
    put("detail-bound-state", holding ? holding.bound_label : null);
    put("detail-bound", holding && ["upper", "lower"].includes(holding.bound_flag) ? holding.bound_label : "");
    put("detail-observations", symbol ? symbol.price_observations : null);
    put("detail-last-date", symbol ? symbol.last_eligible_date : null, "자료 없음");
    for (const card of [...byId("holdings-list").querySelectorAll(".holding-card"), ...byId("composition-bar").children]) {
      const active = card.dataset.code === selectedCode;
      card.setAttribute("aria-pressed", String(active));
      card.tabIndex = active ? 0 : -1;
    }
  };

  const selectionFeedback = (kind) => {
    const detail = byId("holding-detail");
    // CSS can replay a brief accent without delaying values or adding timers.
    detail.dataset.selectionPhase = detail.dataset.selectionPhase === "a" ? "b" : "a";
    audio.effect(kind);
  };

  const selectCode = (code, focus = false, focusGroup = "holdings-list") => {
    const changed = code !== selectedCode;
    if (changed) {
      selectedCode = code;
      refreshDetail();
    }
    if (focus) {
      const active = Array.from(byId(focusGroup).children).find((card) => card.dataset.code === code);
      if (active) active.focus();
    }
    if (!changed) return;
    selectionFeedback("select");
    const holding = current().holdings.find((item) => item.code === code);
    announce(`${identityFor(code)} 선택. 목표비중 ${holding ? holding.weight_display : "미산출"}.`);
  };

  const navigateAssets = (event, index, focusGroup) => {
    const actions = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
    let destination;
    if (event.key in actions) destination = (index + actions[event.key] + data.selected_codes.length) % data.selected_codes.length;
    else if (event.key === "Home") destination = 0;
    else if (event.key === "End") destination = data.selected_codes.length - 1;
    else return;
    event.preventDefault();
    selectCode(data.selected_codes[destination], true, focusGroup);
  };

  const refreshScenario = (speak = false) => {
    const scenario = current();
    tabs.forEach((tab, index) => {
      tab.setAttribute("aria-selected", String(index === scenarioIndex));
      tab.tabIndex = index === scenarioIndex ? 0 : -1;
    });
    byId("formation-panel").setAttribute("aria-labelledby", tabs[scenarioIndex].id);
    put("volatility", scenario.volatility_display);
    const priorCovariance = byId("current-covariance-fingerprint");
    if (priorCovariance) priorCovariance.remove();
    if (scenario.covariance_fingerprint) {
      const row = node("div");
      row.id = "current-covariance-fingerprint";
      row.append(node("dt", "", "현재 시나리오 공분산 fingerprint"), node("dd", "", scenario.covariance_fingerprint));
      byId("fingerprints").append(row);
    }
    const notice = byId("scenario-notice");
    notice.replaceChildren();
    notice.hidden = scenario.status === "succeeded";
    if (!notice.hidden) {
      notice.append(node("strong", "", "이 시나리오의 목표비중은 산출되지 않았습니다."));
      if (scenario.failure) {
        notice.append(node("p", "", scenario.failure.message), node("code", "", scenario.failure.code));
      } else if (data.reasons.length) {
        for (const reason of data.reasons) notice.append(node("p", "", `${reason.code}: ${reason.message}`));
      } else {
        notice.append(node("p", "", "공통 준비·계산 상태에서 실행되지 않은 시나리오입니다. 아래 계산 근거를 확인해 주세요."));
      }
    }
    const list = byId("holdings-list");
    const exact = byId("exact-weights");
    const composition = byId("composition-bar");
    composition.replaceChildren();
    byId("composition").hidden = scenario.status !== "succeeded";
    list.replaceChildren();
    exact.replaceChildren();
    data.selected_codes.forEach((code, index) => {
      const holding = scenario.holdings.find((item) => item.code === code);
      const card = node("button", `holding-card${holding ? "" : " unavailable"}`);
      card.type = "button";
      card.dataset.code = code;
      card.style.setProperty("--asset-color", colorFor(code));
      card.setAttribute("aria-label", `${identityFor(code)}, 목표비중 ${holding ? holding.weight_display : "미산출"}, 상세 보기`);
      const swatch = node("span", "asset-swatch");
      swatch.setAttribute("aria-hidden", "true");
      card.append(swatch);
      const identity = node("div", "holding-identity");
      identity.append(node("span", "holding-name", nameFor(code)), node("span", "holding-code", code));
      card.append(identity, node("span", "holding-weight", holding ? holding.weight_display : "미산출"));
      const track = node("div", "weight-track");
      track.setAttribute("aria-hidden", "true");
      const fill = node("div", "weight-fill");
      // Number is used only to paint the bar. Displayed values come from Python.
      fill.style.width = holding ? `${Math.max(0, Math.min(100, Number(holding.bar_percent) / 20 * 100))}%` : "0%";
      track.append(fill);
      card.append(track);
      card.addEventListener("click", () => selectCode(code));
      card.addEventListener("keydown", (event) => navigateAssets(event, index, "holdings-list"));
      list.append(card);
      if (holding) {
        const row = node("div", "exact-weight");
        row.append(node("span", "", identityFor(code)), node("code", "", holding.weight));
        exact.append(row);
        const segment = node("button", "composition-segment");
        segment.type = "button";
        segment.dataset.code = code;
        segment.style.setProperty("--asset-color", colorFor(code));
        // The source percentage sets actual portfolio width; never normalized.
        segment.style.width = `${Number(holding.bar_percent)}%`;
        segment.setAttribute("aria-label", `${identityFor(code)}, 전체 포트폴리오의 ${holding.weight_display}, 원본 Decimal 비중 ${holding.weight}`);
        segment.title = `${identityFor(code)} · ${holding.weight_display}`;
        if (Number(holding.bar_percent) >= 8) segment.append(node("span", "segment-weight", holding.weight_display));
        segment.addEventListener("click", () => selectCode(code));
        segment.addEventListener("keydown", (event) => navigateAssets(event, index, "composition-bar"));
        composition.append(segment);
      }
    });
    if (!data.selected_codes.length) list.append(node("p", "small-note", "선정된 종목이 없습니다."));
    if (!scenario.holdings.length) exact.append(node("p", "evidence-description", "현재 시나리오의 목표비중 없음."));
    refreshDetail();
    if (speak) {
      selectionFeedback(scenario.status === "succeeded" ? "tab" : "caution");
      announce(`${scenario.label}. ${scenario.status === "succeeded" ? "계산 성공" : "목표비중 미산출"}. ${selectedCode ? `선택 종목 ${identityFor(selectedCode)} 유지.` : ""}`);
    }
  };

  data.scenarios.forEach((scenario, index) => {
    const tab = node("button", "scenario-tab");
    tab.type = "button";
    tab.id = `scenario-tab-${index}`;
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-controls", "formation-panel");
    tab.append(node("span", "tab-index", String(index + 1).padStart(2, "0")));
    const copy = node("span", "tab-copy");
    copy.append(node("span", "tab-label", scenario.label), node("span", "tab-volatility", `연환산 변동성 ${scenario.volatility_display === null ? "미산출" : scenario.volatility_display}`));
    const state = node("span", `tab-state${scenario.status === "succeeded" ? "" : " failure"}`);
    state.setAttribute("aria-hidden", "true");
    tab.append(copy, state, node("span", "tab-status", scenario.status === "succeeded" ? "산출 완료" : "미산출"));
    tab.title = scenario.failure ? `${scenario.kind} · ${scenario.failure.code}: ${scenario.failure.message}` : scenario.kind;
    tab.addEventListener("click", () => {
      if (scenarioIndex === index) return;
      scenarioIndex = index;
      refreshScenario(true);
    });
    tab.addEventListener("keydown", (event) => {
      let destination;
      if (event.key === "ArrowRight") destination = (index + 1) % tabs.length;
      else if (event.key === "ArrowLeft") destination = (index + tabs.length - 1) % tabs.length;
      else if (event.key === "Home") destination = 0;
      else if (event.key === "End") destination = tabs.length - 1;
      else return;
      event.preventDefault();
      if (scenarioIndex !== destination) {
        scenarioIndex = destination;
        refreshScenario(true);
      }
      tabs[destination].focus();
    });
    tabs.push(tab);
    byId("scenario-tabs").append(tab);
  });
  refreshScenario();
  byId("evidence-panel").addEventListener("toggle", () => { audio.effect("evidence"); });
  const dialog = byId("settings-dialog");
  byId("settings-open").addEventListener("click", () => { dialog.showModal(); audio.effect("inspect"); });
  const closeSettings = () => { audio.effect("confirm"); dialog.close(); byId("settings-open").focus(); };
  byId("settings-close").addEventListener("click", closeSettings);
  byId("settings-done").addEventListener("click", closeSettings);
  byId("audio-enable").addEventListener("click", async () => { if (await audio.enable()) audio.effect("confirm"); });
  byId("audio-mute").addEventListener("click", () => audio.mute());
  byId("audio-preview").addEventListener("click", () => audio.preview());
  byId("music-start").addEventListener("click", () => audio.startMusic());
  byId("music-stop").addEventListener("click", () => audio.stopMusic());
  for (const [id, key] of [["sfx-volume", "sfxVolume"], ["music-volume", "musicVolume"]]) {
    byId(id).value = String(preferences[key]);
    put(`${id}-label`, `${preferences[key]}%`);
    byId(id).addEventListener("input", (event) => {
      preferences[key] = Number(event.target.value);
      put(`${id}-label`, `${preferences[key]}%`);
      audio.setVolumes(preferences.sfxVolume / 100, preferences.musicVolume / 100);
      savePreferences();
    });
  }
  byId("reduce-motion").checked = preferences.reduceMotion;
  document.documentElement.classList.toggle("reduced-motion", preferences.reduceMotion);
  byId("reduce-motion").addEventListener("change", (event) => {
    preferences.reduceMotion = event.target.checked;
    document.documentElement.classList.toggle("reduced-motion", preferences.reduceMotion);
    savePreferences();
  });
  if (desktop) window.parent.postMessage({ type: "phalanx-room-ready" }, "*");
})();
