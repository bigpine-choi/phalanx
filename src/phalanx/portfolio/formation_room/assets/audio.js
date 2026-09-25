/* Original synthesized prototype soundtrack. Replace this layer for final audio. */
(() => {
  "use strict";
  const AudioContextType = window.AudioContext || window.webkitAudioContext;
  const BEAT = 60 / 66;
  const STEPS_PER_BAR = 8;
  // Eight bars: Dm(add9), Bbmaj7, F(add9), Csus2, Gm9, Bbmaj7, Dm9, Asus4.
  const CHORDS = [
    [50, 57, 60, 64], [46, 53, 57, 60], [41, 53, 57, 67], [48, 55, 62, 64],
    [43, 53, 57, 62], [46, 53, 60, 65], [50, 57, 60, 64], [45, 52, 57, 62]
  ];
  const MELODY = [
    [74, null, 76, 77, null, 81, 77, null], [77, null, 74, null, 72, 74, null, null],
    [72, null, 76, 79, null, 77, 76, null], [74, null, 79, null, 76, 74, null, null],
    [70, null, 74, 77, null, 81, 79, null], [77, null, 74, null, 72, 69, null, null],
    [74, null, 76, 77, 81, null, 77, 76], [74, null, 73, null, 69, null, null, null]
  ];
  const EFFECTS = {
    select: [[74, 0, .09, .11], [81, .06, .14, .06]],
    tab: [[62, 0, .13, .10], [69, .08, .16, .08], [74, .15, .20, .07]],
    evidence: [[69, 0, .11, .09], [74, .07, .16, .07]],
    confirm: [[74, 0, .14, .10], [78, .08, .18, .08], [81, .16, .25, .06]],
    inspect: [[81, 0, .17, .07], [86, .10, .23, .05]],
    caution: [[57, 0, .18, .08], [62, .14, .25, .07]]
  };
  const hz = (midi) => 440 * Math.pow(2, (midi - 69) / 12);
  const clamp = (value) => Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0;

  const scheduleVoice = (context, destination, active, options) => {
    const start = options.start;
    const duration = options.duration;
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    const filter = context.createBiquadFilter();
    const pan = context.createStereoPanner ? context.createStereoPanner() : null;
    oscillator.type = options.type || "sine";
    oscillator.frequency.setValueAtTime(hz(options.midi), start);
    filter.type = "lowpass";
    filter.frequency.setValueAtTime(options.cutoff || 1900, start);
    filter.Q.value = .5;
    const attack = Math.min(options.attack || .014, duration * .35);
    gain.gain.setValueAtTime(0, start);
    gain.gain.linearRampToValueAtTime(options.level, start + attack);
    gain.gain.exponentialRampToValueAtTime(.0001, start + duration);
    oscillator.connect(filter);
    filter.connect(gain);
    if (pan) {
      pan.pan.value = options.pan || 0;
      gain.connect(pan);
      pan.connect(destination);
    } else gain.connect(destination);
    const voice = { oscillator, gain, filter, pan };
    active.add(voice);
    oscillator.onended = () => {
      oscillator.disconnect();
      filter.disconnect();
      gain.disconnect();
      if (pan) pan.disconnect();
      active.delete(voice);
    };
    oscillator.start(start);
    oscillator.stop(start + duration + .02);
  };

  const scheduleMusicStep = (context, destination, active, step, time) => {
    const bar = Math.floor(step / STEPS_PER_BAR) % CHORDS.length;
    const slot = step % STEPS_PER_BAR;
    if (slot === 0) {
      CHORDS[bar].forEach((midi, index) => {
        scheduleVoice(context, destination, active, {
          midi, start: time, duration: BEAT * 4.3, attack: .55,
          level: index === 0 ? .21 : .12, type: "sine", cutoff: 1200,
          pan: index === 0 ? 0 : (index - 2) * .38
        });
      });
    }
    const midi = MELODY[bar][slot];
    if (midi !== null) {
      scheduleVoice(context, destination, active, {
        midi, start: time, duration: BEAT * 1.5, attack: .055,
        level: .105, type: "triangle", cutoff: 1450, pan: slot % 2 ? .15 : -.15
      });
      // A quiet octave overtone gives the bell-like melody a soft tail.
      scheduleVoice(context, destination, active, {
        midi: midi + 12, start: time + .014, duration: BEAT * 1.8,
        attack: .04, level: .019, type: "sine", cutoff: 2200, pan: -.18
      });
    }
  };

  const createController = (options = {}) => {
    let context = null;
    let master = null;
    let effectsGain = null;
    let musicGain = null;
    let enabled = false;
    let starting = false;
    let musicPlaying = false;
    let timer = null;
    let nextStep = 0;
    let nextTime = 0;
    let lastEffect = -Infinity;
    let previewIndex = 0;
    let disposed = false;
    let generation = 0;
    let sfxVolume = clamp(options.sfxVolume === undefined ? .22 : options.sfxVolume);
    let musicVolume = clamp(options.musicVolume === undefined ? .16 : options.musicVolume);
    const musicVoices = new Set();
    const effectVoices = new Set();
    const notice = (message) => { if (options.onNotice) options.onNotice(message); };
    const state = () => ({ enabled, starting, musicPlaying, supported: Boolean(AudioContextType), activeMusicVoices: musicVoices.size, activeEffectVoices: effectVoices.size, scheduledTimer: timer !== null });
    const changed = () => { if (options.onChange) options.onChange(state()); };
    const stopVoices = (voices, immediate = false) => {
      if (!context) return;
      const now = context.currentTime;
      for (const voice of voices) {
        try {
          if (immediate) {
            voice.gain.gain.cancelScheduledValues(now);
            voice.gain.gain.setValueAtTime(0, now);
          } else {
            if (voice.gain.gain.cancelAndHoldAtTime) voice.gain.gain.cancelAndHoldAtTime(now);
            else {
              voice.gain.gain.cancelScheduledValues(now);
              voice.gain.gain.setValueAtTime(Math.min(.2, voice.gain.gain.value), now);
            }
            voice.gain.gain.linearRampToValueAtTime(0, now + .025);
          }
          voice.oscillator.stop(now + (immediate ? 0 : .03));
        } catch (_) { /* A completed voice can race a stop request. */ }
        if (immediate) {
          voice.oscillator.disconnect();
          voice.filter.disconnect();
          voice.gain.disconnect();
          if (voice.pan) voice.pan.disconnect();
        }
      }
      if (immediate) voices.clear();
    };
    const stopMusic = () => {
      generation += 1;
      starting = false;
      if (timer !== null) window.clearInterval(timer);
      timer = null;
      musicPlaying = false;
      stopVoices(musicVoices);
      nextStep = 0;
      changed();
    };
    const mute = () => {
      enabled = false;
      stopMusic();
      stopVoices(effectVoices);
      if (master && context) master.gain.setTargetAtTime(0, context.currentTime, .008);
      changed();
    };
    const ensureContext = () => {
      if (context) return;
      const candidate = new AudioContextType();
      try {
        const candidateMaster = candidate.createGain();
        candidateMaster.gain.value = 0;
        const limiter = candidate.createDynamicsCompressor();
        limiter.threshold.value = -14;
        limiter.knee.value = 12;
        limiter.ratio.value = 5;
        limiter.attack.value = .006;
        limiter.release.value = .2;
        candidateMaster.connect(limiter);
        limiter.connect(candidate.destination);
        const candidateEffects = candidate.createGain();
        candidateEffects.gain.value = sfxVolume;
        candidateEffects.connect(candidateMaster);
        const candidateMusic = candidate.createGain();
        candidateMusic.gain.value = musicVolume;
        candidateMusic.connect(candidateMaster);
        context = candidate;
        master = candidateMaster;
        effectsGain = candidateEffects;
        musicGain = candidateMusic;
      } catch (error) {
        candidate.close().catch(() => {});
        throw error;
      }
    };
    const audioFailure = () => {
      mute();
      stopVoices(musicVoices, true);
      stopVoices(effectVoices, true);
      notice("음향을 재생하지 못해 정지했습니다. 화면 탐색은 계속 사용할 수 있습니다.");
    };
    const enable = async () => {
      if (disposed || document.hidden) return false;
      if (!AudioContextType) { notice("Web Audio 미지원: 화면 탐색은 그대로 사용할 수 있습니다."); return false; }
      const request = ++generation;
      starting = true;
      changed();
      try {
        ensureContext();
        const requestedContext = context;
        await requestedContext.resume();
        if (disposed || document.hidden || request !== generation || context !== requestedContext || requestedContext.state !== "running") {
          return false;
        }
        enabled = true;
        master.gain.setTargetAtTime(.7, context.currentTime, .015);
        notice("");
        return true;
      } catch (_) {
        // A cancelled request may settle after a fresh start. It must not mute
        // that request, clear its pending state, or close its shared context.
        if (request !== generation || disposed) return false;
        mute();
        notice("음향을 시작하지 못했습니다. 브라우저의 음향 허용 상태를 확인해 주세요. 화면 탐색은 계속 사용할 수 있습니다.");
        return false;
      } finally {
        if (request === generation) {
          starting = false;
          changed();
        }
      }
    };
    const effect = (kind) => {
      if (!enabled || !context || context.state !== "running" || document.hidden || !EFFECTS[kind]) return;
      const now = context.currentTime;
      if (now - lastEffect < .085 || effectVoices.size >= 12) return;
      lastEffect = now;
      try {
        for (const [midi, offset, duration, level] of EFFECTS[kind]) {
          scheduleVoice(context, effectsGain, effectVoices, { midi, start: now + offset, duration, level, type: "sine" });
        }
      } catch (_) { audioFailure(); }
    };
    const tick = () => {
      if (!enabled || !musicPlaying || !context || document.hidden) return;
      // Bound catch-up after a stalled tab: never schedule an accumulated backlog.
      if (nextTime < context.currentTime) nextTime = context.currentTime + .02;
      try {
        while (nextTime < context.currentTime + .2) {
          scheduleMusicStep(context, musicGain, musicVoices, nextStep, nextTime);
          nextStep = (nextStep + 1) % (CHORDS.length * STEPS_PER_BAR);
          nextTime += BEAT / 2;
        }
      } catch (_) { audioFailure(); }
    };
    const startMusic = async () => {
      if (musicPlaying) return;
      const pending = enable();
      const request = generation;
      if (!await pending || request !== generation) return;
      // Re-check after resume: two rapid explicit clicks must not create two timers.
      if (musicPlaying || disposed || document.hidden) return;
      musicPlaying = true;
      nextStep = 0;
      nextTime = context.currentTime + .035;
      tick();
      if (!musicPlaying) return;
      timer = window.setInterval(tick, 75);
      changed();
    };
    const preview = async () => {
      if (!await enable()) return;
      const kinds = Object.keys(EFFECTS);
      effect(kinds[previewIndex % kinds.length]);
      if (!enabled) return;
      previewIndex += 1;
      notice(`효과음 미리듣기 ${previewIndex % kinds.length || kinds.length} / ${kinds.length} · 누를 때마다 다른 소리를 들을 수 있습니다.`);
    };
    const setVolumes = (sfx, music) => {
      sfxVolume = clamp(sfx);
      musicVolume = clamp(music);
      if (context) {
        try {
          effectsGain.gain.setTargetAtTime(sfxVolume, context.currentTime, .025);
          musicGain.gain.setTargetAtTime(musicVolume, context.currentTime, .025);
        } catch (_) { audioFailure(); }
      }
    };
    const onVisibility = () => {
      if (!document.hidden) return;
      const hadAudio = enabled || starting;
      mute();
      stopVoices(musicVoices, true);
      stopVoices(effectVoices, true);
      if (context) context.suspend().catch(() => {});
      if (hadAudio) notice("화면이 숨겨져 음향을 정지했습니다. 소리 켜기 또는 음악 시작으로 직접 재개해 주세요.");
    };
    const dispose = () => {
      disposed = true;
      mute();
      stopVoices(musicVoices, true);
      stopVoices(effectVoices, true);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", onPageHide);
      if (context) context.close().catch(() => {});
    };
    const onPageHide = (event) => {
      if (!event.persisted) { dispose(); return; }
      // A page restored from the back/forward cache stays usable but always silent.
      mute();
      stopVoices(musicVoices, true);
      stopVoices(effectVoices, true);
      if (context) context.suspend().catch(() => {});
    };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", onPageHide);
    changed();
    return { enable, mute, effect, preview, startMusic, stopMusic, setVolumes, dispose, getState: state };
  };

  // Deterministic offline renderer for waveform inspection and reproducible WAV export.
  // It does not create or resume a playback AudioContext and never autoplays.
  const renderPreview = async (seconds = 32) => {
    const OfflineType = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    if (!OfflineType) throw new Error("Offline audio rendering is unavailable.");
    const duration = Math.max(1, Math.min(60, Number(seconds) || 32));
    const context = new OfflineType(2, Math.ceil(duration * 44100), 44100);
    const gain = context.createGain();
    gain.gain.value = .16 * .7;
    gain.connect(context.destination);
    const voices = new Set();
    for (let step = 0, time = .05; time < duration; step += 1, time += BEAT / 2) {
      scheduleMusicStep(context, gain, voices, step, time);
    }
    return context.startRendering();
  };
  window.PhalanxAudio = Object.freeze({ createController, renderPreview });
})();
