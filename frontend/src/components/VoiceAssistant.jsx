import React, { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { MessageCircle, X, Mic, Send, Volume2, VolumeX, Loader2, Phone } from 'lucide-react';
import CallView from './CallView';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const SUGGESTIONS = [
  'Где купить парацетамол?',
  'Сколько стоит Нурофен?',
  'Аптеки рядом с метро Тверская',
  'Есть ли Витамин D3?',
];

function getOrCreateSessionId() {
  let sid = localStorage.getItem('aptekaa_voice_sid');
  if (!sid) {
    sid = (crypto && crypto.randomUUID) ? crypto.randomUUID() : `sid-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    localStorage.setItem('aptekaa_voice_sid', sid);
  }
  return sid;
}

export default function VoiceAssistant() {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState('chat'); // 'chat' | 'call'
  const [messages, setMessages] = useState([
    { role: 'assistant', content: 'Здравствуйте! Я голосовой помощник АптекаА. Назовите лекарство или задайте вопрос — я подскажу цены и ближайшие аптеки.' },
  ]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [listening, setListening] = useState(false);
  const [ttsEnabled, setTtsEnabled] = useState(true);
  const [error, setError] = useState('');
  const [supported, setSupported] = useState({ stt: false });

  const recognitionRef = useRef(null);
  const messagesEndRef = useRef(null);
  const sessionIdRef = useRef(getOrCreateSessionId());
  const audioRef = useRef(null);
  const audioUrlRef = useRef(null);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    setSupported({ stt: !!SR });

    if (SR) {
      const rec = new SR();
      rec.lang = 'ru-RU';
      rec.continuous = false;
      rec.interimResults = false;
      rec.maxAlternatives = 1;
      rec.onresult = (e) => {
        const text = e.results[0][0].transcript;
        setInput(text);
        setListening(false);
        setTimeout(() => sendMessage(text), 50);
      };
      rec.onerror = (e) => {
        setListening(false);
        if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
          setError('Доступ к микрофону запрещён. Разрешите его в настройках браузера.');
        } else if (e.error === 'no-speech') {
          setError('Я не услышал. Попробуйте ещё раз.');
        }
      };
      rec.onend = () => setListening(false);
      recognitionRef.current = rec;
    }

    // Prepare a single Audio element for TTS playback
    audioRef.current = new Audio();

    return () => {
      try { recognitionRef.current && recognitionRef.current.abort(); } catch (_) {}
      stopSpeaking();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, sending]);

  const stopSpeaking = () => {
    try {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current.src = '';
      }
      if (audioUrlRef.current) {
        URL.revokeObjectURL(audioUrlRef.current);
        audioUrlRef.current = null;
      }
    } catch (_) {}
  };

  const speak = async (text) => {
    if (!ttsEnabled || !text || !audioRef.current) return;
    try {
      stopSpeaking();
      const resp = await axios.post(
        `${API}/voice/tts`,
        { text, voice: 'alena', emotion: 'good' },
        { responseType: 'blob', timeout: 25000 }
      );
      const url = URL.createObjectURL(resp.data);
      audioUrlRef.current = url;
      audioRef.current.src = url;
      // Some browsers require play() to be triggered from user gesture; the
      // interaction (sending msg / opening dialog) usually counts as one.
      const p = audioRef.current.play();
      if (p && typeof p.catch === 'function') {
        p.catch(() => {/* ignore autoplay blocks */});
      }
    } catch (e) {
      // Soft fail – text is still shown on screen
      // eslint-disable-next-line no-console
      console.warn('TTS error', e?.message || e);
    }
  };

  const sendMessage = async (overrideText) => {
    const text = (overrideText ?? input).trim();
    if (!text || sending) return;
    setError('');
    setInput('');
    setMessages((prev) => [...prev, { role: 'user', content: text }]);
    setSending(true);
    try {
      const { data } = await axios.post(`${API}/voice/chat`, {
        session_id: sessionIdRef.current,
        message: text,
      }, { timeout: 30000 });
      const reply = data?.reply || 'Извините, я не смог ответить.';
      setMessages((prev) => [...prev, { role: 'assistant', content: reply }]);
      speak(reply);
    } catch (e) {
      const fallback = 'Похоже, связь нестабильна. Попробуйте ещё раз через минуту.';
      setMessages((prev) => [...prev, { role: 'assistant', content: fallback }]);
      setError('Не удалось получить ответ. Проверьте интернет.');
    } finally {
      setSending(false);
    }
  };

  const startListening = () => {
    if (!recognitionRef.current || listening) return;
    setError('');
    stopSpeaking();
    try {
      recognitionRef.current.start();
      setListening(true);
    } catch (_) {}
  };

  const stopListening = () => {
    if (!recognitionRef.current) return;
    try { recognitionRef.current.stop(); } catch (_) {}
    setListening(false);
  };

  const toggleOpen = () => {
    if (open) stopSpeaking();
    setOpen((o) => !o);
  };

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <>
      {/* Floating launcher */}
      {!open && (
        <button
          data-testid="voice-assistant-launcher"
          onClick={toggleOpen}
          className="fixed bottom-20 right-5 z-50 flex items-center gap-2 rounded-full bg-brand-green text-white px-5 py-3 shadow-card-hover hover:bg-brand-green-dark transition-all"
          aria-label="Открыть голосового помощника"
        >
          <MessageCircle className="w-5 h-5" />
          <span className="hidden sm:inline font-semibold text-sm">Голосовой помощник</span>
        </button>
      )}

      {/* Dialog */}
      {open && (
        <div
          data-testid="voice-assistant-dialog"
          className="fixed bottom-20 right-5 z-50 w-[calc(100vw-2.5rem)] sm:w-[380px] max-h-[80vh] bg-white rounded-2xl shadow-card-hover border border-slate-200 flex flex-col overflow-hidden"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 bg-brand-green text-white">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full bg-white/20 flex items-center justify-center">
                {mode === 'call' ? <Phone className="w-4 h-4" /> : <MessageCircle className="w-4 h-4" />}
              </div>
              <div>
                <div className="text-sm font-semibold leading-tight">Помощник АптекаА</div>
                <div className="text-[11px] text-white/80 leading-tight">
                  {mode === 'call' ? 'Беседа голосом, как по телефону' : 'Подскажу цены и аптеки'}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-1">
              {mode === 'chat' ? (
                <button
                  data-testid="voice-assistant-switch-call"
                  onClick={() => { stopSpeaking(); setMode('call'); }}
                  className="px-2 py-1 text-[11px] rounded-full bg-white/20 hover:bg-white/30 font-semibold flex items-center gap-1"
                  title="Беспрерывная беседа голосом"
                >
                  <Phone className="w-3 h-3" /> Беседа
                </button>
              ) : (
                <button
                  data-testid="voice-assistant-switch-chat"
                  onClick={() => setMode('chat')}
                  className="px-2 py-1 text-[11px] rounded-full bg-white/20 hover:bg-white/30 font-semibold flex items-center gap-1"
                >
                  <MessageCircle className="w-3 h-3" /> Чат
                </button>
              )}
              {mode === 'chat' && (
                <button
                  data-testid="voice-assistant-toggle-tts"
                  onClick={() => { setTtsEnabled((t) => { if (t) stopSpeaking(); return !t; }); }}
                  className="p-1.5 rounded hover:bg-white/15"
                  title={ttsEnabled ? 'Выключить озвучивание' : 'Включить озвучивание'}
                  aria-label="Озвучивание"
                >
                  {ttsEnabled ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
                </button>
              )}
              <button
                data-testid="voice-assistant-close"
                onClick={toggleOpen}
                className="p-1.5 rounded hover:bg-white/15"
                aria-label="Закрыть"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {mode === 'call' ? (
            <div className="flex-1 min-h-[420px]">
              <CallView onClose={() => setMode('chat')} />
            </div>
          ) : (
          <>
          {/* Messages */}
          <div data-testid="voice-assistant-messages" className="flex-1 overflow-y-auto px-3 py-3 space-y-2 bg-slate-50">
            {messages.map((m, i) => (
              <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div
                  data-testid={`voice-msg-${m.role}`}
                  className={`max-w-[85%] px-3 py-2 rounded-2xl text-sm leading-relaxed ${
                    m.role === 'user'
                      ? 'bg-brand-green text-white rounded-br-sm'
                      : 'bg-white border border-slate-200 text-slate-800 rounded-bl-sm'
                  }`}
                >
                  {m.content}
                </div>
              </div>
            ))}
            {sending && (
              <div className="flex justify-start">
                <div className="px-3 py-2 rounded-2xl bg-white border border-slate-200 text-slate-500 text-sm flex items-center gap-2">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" /> печатает…
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Suggestions */}
          {messages.length <= 1 && !sending && (
            <div className="px-3 pt-2 pb-1 flex flex-wrap gap-1.5 bg-slate-50">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  data-testid="voice-assistant-suggestion"
                  onClick={() => sendMessage(s)}
                  className="text-[11px] px-2.5 py-1 rounded-full border border-slate-300 bg-white hover:border-brand-green hover:text-brand-green transition-colors"
                >
                  {s}
                </button>
              ))}
            </div>
          )}

          {/* Error */}
          {error && (
            <div data-testid="voice-assistant-error" className="px-3 py-1.5 text-[11px] text-red-600 bg-red-50 border-t border-red-100">
              {error}
            </div>
          )}

          {/* Input */}
          <div className="p-2 border-t border-slate-200 bg-white flex items-end gap-1.5">
            {supported.stt ? (
              <button
                data-testid="voice-assistant-mic-button"
                onClick={listening ? stopListening : startListening}
                disabled={sending}
                className={`shrink-0 w-10 h-10 rounded-full flex items-center justify-center transition-colors ${
                  listening
                    ? 'bg-red-500 text-white animate-pulse'
                    : 'bg-brand-green-light text-brand-green hover:bg-brand-green hover:text-white'
                }`}
                title={listening ? 'Остановить запись' : 'Нажмите и говорите'}
                aria-label="Микрофон"
              >
                <Mic className="w-4 h-4" />
              </button>
            ) : null}
            <textarea
              data-testid="voice-assistant-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder={listening ? 'Слушаю…' : 'Напишите или нажмите микрофон'}
              rows={1}
              className="flex-1 resize-none px-3 py-2 text-sm rounded-xl border border-slate-200 focus:border-brand-green focus:outline-none input-focus max-h-24"
            />
            <button
              data-testid="voice-assistant-send"
              onClick={() => sendMessage()}
              disabled={!input.trim() || sending}
              className="shrink-0 w-10 h-10 rounded-full bg-brand-green text-white hover:bg-brand-green-dark disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center"
              aria-label="Отправить"
            >
              {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            </button>
          </div>

          {/* Hint */}
          <div className="px-3 pb-2 text-[10px] text-slate-400 leading-tight bg-white">
            Ответы носят информационный характер. По приёму лекарств — обратитесь к врачу.
          </div>
          </>
          )}
        </div>
      )}
    </>
  );
}
