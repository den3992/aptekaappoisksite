import { useEffect, useRef, useState, useCallback } from 'react';
import axios from 'axios';
import { Phone, PhoneOff, Mic, Loader2 } from 'lucide-react';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

function getOrCreateSessionId() {
  let sid = localStorage.getItem('aptekaa_voice_sid');
  if (!sid) {
    sid = (crypto && crypto.randomUUID) ? crypto.randomUUID() : `sid-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    localStorage.setItem('aptekaa_voice_sid', sid);
  }
  return sid;
}

const SILENCE_TIMEOUT_MS = 900; // user pause before we treat utterance as final
const MAX_UTTERANCE_MS = 15000; // hard cap on a single user turn

/**
 * CallView — continuous phone-call style voice dialog.
 * - Mic stays on the entire call
 * - Web Speech API does STT in the browser (free)
 * - When the user pauses ~0.9s, we send the transcript to /api/voice/chat
 * - We get text back, request /api/voice/tts (Алёна), play audio
 * - If the user starts speaking while audio is playing, audio is stopped (barge-in)
 */
export default function CallView({ onClose }) {
  // ui state
  const [callState, setCallState] = useState('idle'); // idle | starting | listening | thinking | speaking | error
  const [partial, setPartial] = useState('');
  const [transcript, setTranscript] = useState([]); // [{role, text}]
  const [error, setError] = useState('');
  const [elapsed, setElapsed] = useState(0);
  const [supportError, setSupportError] = useState('');

  // refs (stable across renders)
  const sessionIdRef = useRef(getOrCreateSessionId());
  const recognitionRef = useRef(null);
  const audioRef = useRef(null);
  const audioUrlRef = useRef(null);
  const silenceTimerRef = useRef(null);
  const utteranceStartRef = useRef(0);
  const utteranceTimerRef = useRef(null);
  const interimRef = useRef('');
  const finalRef = useRef('');
  const callActiveRef = useRef(false);
  const speakingRef = useRef(false);
  const sendingRef = useRef(false);
  const startedAtRef = useRef(0);
  const elapsedTimerRef = useRef(null);
  const restartGuardRef = useRef(0);
  const stateRef = useRef('idle');
  // Mute mic while the bot is speaking to avoid the bot hearing itself
  // through the speakers (acoustic feedback loop).
  const muteRef = useRef(false);

  const setStateBoth = useCallback((s) => {
    stateRef.current = s;
    setCallState(s);
  }, []);

  // === audio ===
  const stopAudio = useCallback(() => {
    speakingRef.current = false;
    try {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current.currentTime = 0;
        audioRef.current.src = '';
      }
      if (audioUrlRef.current) {
        URL.revokeObjectURL(audioUrlRef.current);
        audioUrlRef.current = null;
      }
    } catch (_) {}
  }, []);

  const playTTS = useCallback(async (text) => {
    if (!text || !audioRef.current || !callActiveRef.current) return;
    try {
      const resp = await axios.post(
        `${API}/voice/tts`,
        { text, voice: 'alena', emotion: 'good' },
        { responseType: 'blob', timeout: 25000 }
      );
      if (!callActiveRef.current) return; // user hung up while we were synthesizing
      const url = URL.createObjectURL(resp.data);
      audioUrlRef.current = url;
      audioRef.current.src = url;

      // Mute microphone while the bot speaks so it doesn't hear itself.
      muteRef.current = true;
      // Drop any partial transcripts buffered before/while we started speaking
      finalRef.current = '';
      interimRef.current = '';
      setPartial('');
      if (silenceTimerRef.current) { clearTimeout(silenceTimerRef.current); silenceTimerRef.current = null; }
      if (utteranceTimerRef.current) { clearTimeout(utteranceTimerRef.current); utteranceTimerRef.current = null; }
      utteranceStartRef.current = 0;
      // Stop recognition; rec.onend will fire and we won't auto-restart
      // because muteRef.current === true. We'll explicitly restart in onended.
      try { recognitionRef.current && recognitionRef.current.stop(); } catch (_) {}

      audioRef.current.onended = () => {
        speakingRef.current = false;
        // small grace period so the tail of the audio playing through speakers
        // is no longer captured by the mic.
        setTimeout(() => {
          if (!callActiveRef.current) return;
          muteRef.current = false;
          finalRef.current = '';
          interimRef.current = '';
          setPartial('');
          // Restart recognition
          try { recognitionRef.current && recognitionRef.current.start(); } catch (_) {}
          if (stateRef.current !== 'idle') setStateBoth('listening');
        }, 250);
      };
      speakingRef.current = true;
      setStateBoth('speaking');
      const p = audioRef.current.play();
      if (p && typeof p.catch === 'function') {
        p.catch(() => {
          speakingRef.current = false;
          muteRef.current = false;
          try { recognitionRef.current && recognitionRef.current.start(); } catch (_) {}
        });
      }
    } catch (e) {
      speakingRef.current = false;
      muteRef.current = false;
      try { recognitionRef.current && recognitionRef.current.start(); } catch (_) {}
      setStateBoth('listening');
    }
  }, [setStateBoth]);

  // === backend chat ===
  const sendUtterance = useCallback(async (text) => {
    if (!text || sendingRef.current || !callActiveRef.current) return;
    sendingRef.current = true;
    setPartial('');
    setTranscript((p) => [...p, { role: 'user', text }]);
    setStateBoth('thinking');
    try {
      const { data } = await axios.post(`${API}/voice/chat`, {
        session_id: sessionIdRef.current,
        message: text,
      }, { timeout: 30000 });
      const reply = data?.reply || '';
      if (!callActiveRef.current) return;
      if (reply) {
        setTranscript((p) => [...p, { role: 'assistant', text: reply }]);
        await playTTS(reply);
      } else {
        setStateBoth('listening');
      }
    } catch (e) {
      if (callActiveRef.current) {
        setError('Связь нестабильна, попробуйте ещё раз');
        setStateBoth('listening');
      }
    } finally {
      sendingRef.current = false;
    }
  }, [playTTS, setStateBoth]);

  const flushUtterance = useCallback(() => {
    const txt = (finalRef.current + ' ' + interimRef.current).trim();
    finalRef.current = '';
    interimRef.current = '';
    if (silenceTimerRef.current) { clearTimeout(silenceTimerRef.current); silenceTimerRef.current = null; }
    if (utteranceTimerRef.current) { clearTimeout(utteranceTimerRef.current); utteranceTimerRef.current = null; }
    utteranceStartRef.current = 0;
    if (txt && txt.length >= 2) sendUtterance(txt);
  }, [sendUtterance]);

  // === recognition lifecycle ===
  const ensureRecognition = useCallback(() => {
    if (recognitionRef.current) return recognitionRef.current;
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) return null;
    const rec = new SR();
    rec.lang = 'ru-RU';
    rec.continuous = true;
    rec.interimResults = true;
    rec.maxAlternatives = 1;

    rec.onresult = (e) => {
      if (!callActiveRef.current) return;
      // While bot is speaking we mute the microphone path entirely so that
      // the bot doesn't hear itself through the speakers and falsely interrupt.
      if (muteRef.current || speakingRef.current) return;
      let interim = '';
      let finalChunk = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const tr = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalChunk += tr; else interim += tr;
      }
      if (interim) interimRef.current = interim;
      if (finalChunk) finalRef.current = (finalRef.current + ' ' + finalChunk).trim();
      setPartial((finalRef.current + ' ' + interimRef.current).trim());

      const haveSpeech = (interimRef.current.trim().length + finalRef.current.trim().length) >= 2;
      if (haveSpeech && !utteranceStartRef.current) {
        utteranceStartRef.current = Date.now();
        utteranceTimerRef.current = setTimeout(flushUtterance, MAX_UTTERANCE_MS);
      }
      // reset silence timer
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
      if (haveSpeech) {
        silenceTimerRef.current = setTimeout(flushUtterance, SILENCE_TIMEOUT_MS);
      }
    };

    rec.onerror = (e) => {
      // Common: "no-speech" (idle), "aborted" (we stopped), "not-allowed" (mic denied)
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        setError('Доступ к микрофону запрещён. Разрешите в настройках браузера.');
        endCall();
      }
    };

    rec.onend = () => {
      // Browser auto-stops periodically; restart while call is active and not muted
      if (callActiveRef.current && !muteRef.current && !speakingRef.current) {
        const now = Date.now();
        if (now - restartGuardRef.current < 200) return; // avoid tight loop
        restartGuardRef.current = now;
        try { rec.start(); } catch (_) {}
      }
    };

    recognitionRef.current = rec;
    return rec;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flushUtterance, stopAudio, setStateBoth]);

  const startCall = useCallback(async () => {
    setError('');
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      setSupportError('Ваш браузер не поддерживает распознавание речи. Используйте Chrome или Edge на десктопе/Android.');
      return;
    }
    setStateBoth('starting');
    callActiveRef.current = true;
    finalRef.current = '';
    interimRef.current = '';
    setPartial('');

    // warm-up audio element to satisfy autoplay policy (call starts on user gesture)
    if (!audioRef.current) audioRef.current = new Audio();

    const rec = ensureRecognition();
    if (!rec) { setSupportError('Не удалось инициализировать микрофон'); setStateBoth('idle'); return; }
    try { rec.start(); } catch (_) {}
    setStateBoth('listening');
    startedAtRef.current = Date.now();
    elapsedTimerRef.current = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAtRef.current) / 1000));
    }, 500);

    // greet first
    const greeting = 'Здравствуйте! Я голосовой помощник АптекаА. Какое лекарство Вы ищете?';
    setTranscript([{ role: 'assistant', text: greeting }]);
    playTTS(greeting);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ensureRecognition, playTTS, setStateBoth]);

  const endCall = useCallback(() => {
    callActiveRef.current = false;
    setStateBoth('idle');
    stopAudio();
    if (silenceTimerRef.current) { clearTimeout(silenceTimerRef.current); silenceTimerRef.current = null; }
    if (utteranceTimerRef.current) { clearTimeout(utteranceTimerRef.current); utteranceTimerRef.current = null; }
    if (elapsedTimerRef.current) { clearInterval(elapsedTimerRef.current); elapsedTimerRef.current = null; }
    setElapsed(0);
    try { recognitionRef.current && recognitionRef.current.stop(); } catch (_) {}
    try { recognitionRef.current && recognitionRef.current.abort(); } catch (_) {}
    recognitionRef.current = null;
  }, [stopAudio, setStateBoth]);

  useEffect(() => () => endCall(), [endCall]);

  const fmtTime = (s) => `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`;
  const isCalling = callState !== 'idle';

  const stateLabel = {
    idle: 'Готов к разговору',
    starting: 'Подключаемся…',
    listening: 'Слушаю…',
    thinking: 'Думаю…',
    speaking: 'Говорю…',
    error: 'Ошибка',
  }[callState];

  return (
    <div data-testid="call-view" className="flex flex-col h-full bg-gradient-to-b from-emerald-50 to-white">
      {/* Status header */}
      <div className="px-4 py-4 text-center border-b border-emerald-100 bg-white/60 backdrop-blur">
        <div className="flex items-center justify-center gap-2">
          <span className={`inline-block w-2 h-2 rounded-full ${isCalling ? 'bg-red-500 animate-pulse' : 'bg-slate-300'}`} />
          <span className="text-sm font-semibold text-slate-700">{stateLabel}</span>
          {isCalling && <span className="text-xs text-slate-500 font-mono">{fmtTime(elapsed)}</span>}
        </div>
      </div>

      {/* Pulse / avatar */}
      <div className="flex-1 flex flex-col items-center justify-center px-4 py-6 overflow-hidden">
        <div className={`relative w-32 h-32 rounded-full flex items-center justify-center
          ${callState === 'speaking' ? 'bg-emerald-500' : callState === 'listening' ? 'bg-emerald-100' : 'bg-slate-100'}
          transition-colors duration-300`}>
          {callState === 'speaking' && (
            <span className="absolute inset-0 rounded-full bg-emerald-400/40 animate-ping" />
          )}
          {callState === 'listening' && (
            <span className="absolute inset-0 rounded-full bg-emerald-300/30 animate-pulse" />
          )}
          {callState === 'thinking' ? (
            <Loader2 className="w-12 h-12 text-emerald-600 animate-spin" />
          ) : callState === 'speaking' ? (
            <span className="text-white text-3xl font-bold">А</span>
          ) : (
            <Mic className={`w-12 h-12 ${callState === 'listening' ? 'text-emerald-600' : 'text-slate-400'}`} />
          )}
        </div>
        <div className="mt-4 text-center text-sm text-slate-600 min-h-[2.5rem] max-w-[300px]">
          {callState === 'idle' && (
            <span>Нажмите «Начать беседу» — задайте вопрос голосом, как по телефону.</span>
          )}
          {callState === 'listening' && partial && (
            <span data-testid="call-partial" className="italic text-slate-700">«{partial}»</span>
          )}
          {callState === 'speaking' && (
            <span className="text-emerald-700">Алёна отвечает… дождитесь окончания фразы</span>
          )}
        </div>

        {/* Last few turns */}
        <div className="mt-4 w-full max-w-md max-h-[140px] overflow-y-auto space-y-1 text-[11px] text-slate-500 px-2">
          {transcript.slice(-6).map((t, i) => (
            <div key={i} className={t.role === 'user' ? 'text-right' : 'text-left'}>
              <span className={t.role === 'user' ? 'text-slate-700' : 'text-emerald-700'}>
                {t.role === 'user' ? 'Вы:' : 'Алёна:'}
              </span>{' '}
              <span>{t.text}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Errors */}
      {(error || supportError) && (
        <div data-testid="call-error" className="px-4 py-2 text-xs text-red-600 bg-red-50 border-t border-red-100 text-center">
          {supportError || error}
        </div>
      )}

      {/* Controls */}
      <div className="p-4 flex items-center justify-center gap-3 border-t border-slate-100 bg-white">
        {!isCalling ? (
          <button
            data-testid="call-start-btn"
            onClick={startCall}
            disabled={!!supportError}
            className="flex items-center gap-2 px-6 py-3 rounded-full bg-emerald-600 hover:bg-emerald-700 text-white font-semibold shadow-md disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Phone className="w-5 h-5" /> Начать беседу
          </button>
        ) : (
          <button
            data-testid="call-end-btn"
            onClick={endCall}
            className="flex items-center gap-2 px-6 py-3 rounded-full bg-red-500 hover:bg-red-600 text-white font-semibold shadow-md"
          >
            <PhoneOff className="w-5 h-5" /> Завершить
          </button>
        )}
        <button
          data-testid="call-back-to-chat"
          onClick={() => { endCall(); onClose && onClose(); }}
          className="text-xs text-slate-500 hover:text-slate-700 underline"
        >
          вернуться в чат
        </button>
      </div>
    </div>
  );
}
