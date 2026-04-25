"use client";
import { useState, useRef, useEffect } from 'react';
import { Shield, Send, MessageSquare, AlertTriangle, Scale, CheckCircle2, User, Search, Zap, Eye, Trash2, Camera, ChevronLeft, ChevronRight } from 'lucide-react';
import { Check, ChevronDown } from 'lucide-react';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { getTranslations, type Locale } from '../locales';
import { PLATFORM_IDS, getPlatform } from '../config/platforms';
import { getPlatformIcon } from '../config/platforms/icons';

const QUICK_ACTION_ICONS = [
  <Camera key="cam" className="w-4 h-4" />,
  <Trash2 key="trash" className="w-4 h-4" />,
  <Zap key="zap" className="w-4 h-4" />,
  <Eye key="eye" className="w-4 h-4" />,
];


export default function Home() {
  const [statusMessage, setStatusMessage] = useState('');
  const [question, setQuestion] = useState('');
  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>(['Instagram']);
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState<{ role: 'user' | 'assistant' | 'system', content: string }[]>([]);
  const allPlatforms = PLATFORM_IDS;
  const [showQuickSelector, setShowQuickSelector] = useState(false);
  const [autoDetect, setAutoDetect] = useState(true);
  const menuRef = useRef<HTMLDivElement>(null);
  const [responseMode, setResponseMode] = useState<'explanation' | 'legal'>('explanation');
  const [isModeMenuOpen, setIsModeMenuOpen] = useState(false);
  const [language, setLanguage] = useState<Locale>('es');
  const t = getTranslations(language);

  const LANGUAGES = [
    { id: 'es' as Locale, label: 'Español', flag: '🇪🇸' },
    { id: 'en' as Locale, label: 'English', flag: '🇬🇧' },
  ];
  const [isLangMenuOpen, setIsLangMenuOpen] = useState(false);

  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setShowQuickSelector(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [showQuickSelector]);
  
  const isAllSelected = selectedPlatforms.length === allPlatforms.length;

  const toggleAll = () => {
    if (isAllSelected) {
      setSelectedPlatforms([]);
    } else {
      setSelectedPlatforms(allPlatforms);
    }
  };

const getBaseFlags = () => {
    const platforms = selectedPlatforms;
    if (platforms.length === 0) return [];
    
    const redFlags = t.redFlags as Record<string, readonly string[]>;
    const flagsByPlatform = platforms.map(p => redFlags[p]);
    const maxLength = Math.max(...flagsByPlatform.map(f => f.length));
    let interleaved: { platform: string; text: string }[] = [];

    for (let i = 0; i < maxLength; i++) {
      platforms.forEach(p => {
        if (redFlags[p]?.[i]) {
          interleaved.push({ platform: p, text: redFlags[p][i] });
        }
      });
    }

    let base = [...interleaved];
    while (base.length > 0 && base.length < 4) {
      base = [...base, ...interleaved];
    }
    return base;
  };

  const baseRedFlags = getBaseFlags();

  const scrollRef = useRef<HTMLDivElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isHovered, setIsHovered] = useState(false);
  const [startX, setStartX] = useState(0);

  // Auto-play
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || isDragging || isHovered || baseRedFlags.length === 0) return;

    let animationId: number;
    const step = () => {
      el.scrollLeft += 0.5;
      
      if (el.scrollLeft >= el.scrollWidth / 2) {
        el.scrollLeft -= el.scrollWidth / 2;
      }
      animationId = requestAnimationFrame(step);
    };
    
    animationId = requestAnimationFrame(step);
    return () => cancelAnimationFrame(animationId);
  }, [isDragging, isHovered, baseRedFlags]);

  const handleMouseDown = (e: React.MouseEvent) => {
    setIsDragging(true);
    setStartX(e.pageX);
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging || !scrollRef.current) return;
    e.preventDefault();
    
    const el = scrollRef.current;
    const x = e.pageX;
    const walk = (startX - x) * 1.5;
    
    let newScrollLeft = el.scrollLeft + walk;

    if (newScrollLeft <= 0) {
      newScrollLeft += el.scrollWidth / 2;
    } else if (newScrollLeft >= el.scrollWidth / 2) {
      newScrollLeft -= el.scrollWidth / 2;
    }

    el.scrollLeft = newScrollLeft;
    setStartX(x);
  };

  const handleMouseUpOrLeave = () => {
    setIsDragging(false);
  };
  
  const chatEndRef = useRef<HTMLDivElement>(null);
  const lastMessageRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    if (loading) {
      chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
    } else if (messages.length > 0) {
      lastMessageRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [messages.length, loading]);

  const togglePlatform = (p: string) => {
    setSelectedPlatforms(prev => 
      prev.includes(p) 
      ? prev.filter(x => x !== p) 
      : [...prev, p]
    );
  };

  const askNinja = async (manualQuestion?: string) => {
    const currentQuestion = manualQuestion || question;

    if (!currentQuestion.trim()) return;

    if (!autoDetect && selectedPlatforms.length === 0) {
      setMessages(prev => [...prev, { role: 'system', content: t.chat.noWeapon }]);
      setQuestion('');
      return;
    }
    
    setQuestion('');
    
    const newUserMessage = { role: 'user' as const, content: currentQuestion };
    setMessages(prev => [...prev, newUserMessage]);
    setLoading(true);
    
    let activePlatforms = selectedPlatforms;
    // Shared correlation ID for all requests belonging to this user question
    const reqId = Math.random().toString(36).slice(2, 10);
    const reqHeaders = { 'Content-Type': 'application/json', 'X-Request-Id': reqId };

    // Single overload warning timer that starts immediately, covering detect-context + ask
    const abortController = new AbortController();
    let overloadShown = false;
    const warnTimeout = setTimeout(() => {
      overloadShown = true;
      setMessages(prev => [...prev, { role: 'system', content: t.chat.overloaded }]);
    }, 30_000);
    const hardTimeout = setTimeout(() => abortController.abort(), 120_000);

    try {
      if (autoDetect) {
        setStatusMessage(t.chat.analyzingIntent); 
        const detectRes = await axios.post(`${backendUrl}/detect-context`, {
          message: currentQuestion,
          current_platforms: selectedPlatforms,
          language: language
        }, { headers: { 'X-Request-Id': reqId }, signal: abortController.signal });

        // Always use the platforms the backend resolved, message or not
        activePlatforms = detectRes.data.platforms;
        setSelectedPlatforms(activePlatforms);
        if (detectRes.data.message) {
          setMessages(prev => [...prev, { role: 'system', content: detectRes.data.message }]);
        }
      }

      setStatusMessage(t.chat.consultingNinjas);

      const chatHistoryForBackend = messages.filter(m => m.role !== 'system');
      
      const fetchStart = performance.now();

      const response = await fetch(`${backendUrl}/ask`, {
        method: 'POST',
        headers: reqHeaders,
        body: JSON.stringify({
          platforms: activePlatforms,
          messages: [...chatHistoryForBackend, newUserMessage],
          mode: responseMode,
          language: language
        }),
        signal: abortController.signal,
      });

      if (!response.body) throw new Error('No stream received');

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let done = false;
      let text = '';
      let isFirstChunk = true;
      let ttfbLogged = false;

      while (!done) {
        const { value, done: doneReading } = await reader.read();
        done = doneReading;
        
        if (value) {
          // First byte arrived — cancel both timers
          clearTimeout(warnTimeout);
          clearTimeout(hardTimeout);
          if (!ttfbLogged && process.env.NODE_ENV === 'development') {
            console.log(`[TTFB] /ask stream first byte: ${(performance.now() - fetchStart).toFixed(0)}ms`);
            ttfbLogged = true;
          }
          text += decoder.decode(value, { stream: true });
          
          if (isFirstChunk) {
            setStatusMessage('');
            setLoading(false);
            // If overload warning was already shown, replace it with the real answer
            setMessages(prev => {
              const withoutWarn = overloadShown ? prev.slice(0, -1) : prev;
              return [...withoutWarn, { role: 'assistant', content: text }];
            });
            isFirstChunk = false;
          } else {
            setMessages(prev => {
              const newMessages = [...prev];
              newMessages[newMessages.length - 1].content = text;
              return newMessages;
            });
          }
        }
      }
      
      // Safety: if connection closes before any data
      if (isFirstChunk) {
        clearTimeout(warnTimeout);
        clearTimeout(hardTimeout);
        setStatusMessage('');
        setLoading(false);
      }
      
    } catch (err) {
      clearTimeout(warnTimeout);
      clearTimeout(hardTimeout);
      const isAbort = err instanceof Error && err.name === 'AbortError';
      if (isAbort) {
        // Hard abort after 2 min — add a final error below the overload warning
        setMessages(prev => [...prev, { role: 'system', content: t.chat.connectionError }]);
      } else {
        // Network error or detect-context failure — remove overload warning if it was shown
        setMessages(prev => {
          const withoutWarn = overloadShown ? prev.slice(0, -1) : prev;
          return [...withoutWarn, { role: 'system', content: t.chat.connectionError }];
        });
      }
      setStatusMessage('');
      setLoading(false);
    }
  };

  const MODES = [
    { 
      id: 'explanation', 
      title: t.modes.explanation.title, 
      description: t.modes.explanation.description 
    },
    { 
      id: 'legal', 
      title: t.modes.legal.title, 
      description: t.modes.legal.description 
    }
  ];

  return (
    <main className="min-h-screen bg-[#09090b] text-zinc-100 p-4 md:p-12 font-sans">
      <div className="max-w-4xl mx-auto flex flex-col min-h-[80vh]">

        {/* Language Selector */}
        <div className="absolute top-4 right-4 z-50">
          <div className="relative">
            {/* Main Button */}
            <button
              onClick={() => setIsLangMenuOpen(!isLangMenuOpen)}
              className="flex items-center gap-2 px-3 py-2 bg-zinc-900/80 backdrop-blur-md border border-zinc-800 rounded-full shadow-lg hover:bg-zinc-800 transition-all text-sm font-bold uppercase tracking-wider"
            >
              <span>{LANGUAGES.find(l => l.id === language)?.flag}</span>
              <span className="text-zinc-300">{language}</span>
              <ChevronDown className={`w-3 h-3 text-zinc-500 transition-transform duration-300 ${isLangMenuOpen ? 'rotate-180' : ''}`} />
            </button>

            {/* Dropdown Menu */}
            {isLangMenuOpen && (
              <>
                {/* Backdrop */}
                <div 
                  className="fixed inset-0 z-10" 
                  onClick={() => setIsLangMenuOpen(false)} 
                />
                
                <div className="absolute right-0 mt-2 w-40 bg-zinc-900 border border-zinc-800 rounded-2xl shadow-2xl py-1.5 z-20 animate-in fade-in zoom-in-95 duration-200">
                  {LANGUAGES.map((lang) => (
                    <button
                      key={lang.id}
                      onClick={() => {
                        setLanguage(lang.id);
                        setIsLangMenuOpen(false);
                      }}
                      className={`w-full flex items-center justify-between px-4 py-2.5 text-sm transition-colors ${
                        language === lang.id 
                          ? 'text-emerald-400 bg-emerald-500/5' 
                          : 'text-zinc-400 hover:text-white hover:bg-zinc-800'
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        <span>{lang.flag}</span>
                        <span className="font-medium">{lang.label}</span>
                      </div>
                      {language === lang.id && <Check className="w-4 h-4" />}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
        
        {/* Header Section */}
        <header className="flex flex-col items-center mb-8 text-center">
          <div className="bg-emerald-500/10 p-3 rounded-2xl mb-4">
            <Shield className="w-10 h-10 text-emerald-500" />
          </div>
          <h1 className="text-3xl font-black tracking-tight mb-2">T&C NINJA</h1>
          <div className="text-center space-y-2">
            <p className="text-zinc-400 text-sm max-w-md mx-auto mb-6">
              {t.header.subtitle}
            </p>
          </div>
          <div className="flex gap-2 flex-wrap justify-center">
            
            {/* Toggle All Button */}
            <button
              onClick={toggleAll}
              className={`py-2 px-4 rounded-xl border transition-all duration-300 font-bold tracking-wide ${
                isAllSelected 
                ? 'bg-zinc-200 text-black border-zinc-200 shadow-[0_0_15px_rgba(228,228,231,0.3)] scale-105' 
                : 'bg-zinc-900 text-zinc-400 border-zinc-700 hover:border-zinc-500 hover:text-zinc-200'
              }`}
            >
              {isAllSelected ? t.platforms.none : t.platforms.all}
            </button>

            {/* Divider */}
            <div className="w-px bg-zinc-800 mx-1"></div>

            {/* Platform Buttons */}
            {allPlatforms.map((p) => {
              const Icon = getPlatformIcon(p);
              return (
                <button 
                  key={p}
                  onClick={() => togglePlatform(p)}
                  className={`py-2 px-4 rounded-xl border transition-all duration-300 flex items-center gap-2 ${
                    selectedPlatforms.includes(p) 
                    ? 'bg-emerald-500 text-black border-emerald-500 shadow-lg scale-105' 
                    : 'bg-zinc-900 text-zinc-500 border-zinc-800 opacity-60 hover:opacity-100'
                  }`}
                >
                  {Icon && <Icon className="w-4 h-4" />}
                  {p}
                </button>
              );
            })}
          </div>
        </header>

        <div className="flex-1 space-y-6 mb-8 min-h-[400px]">
          
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center mt-10 space-y-10 animate-in fade-in zoom-in duration-500 px-4">
              
              {/* Red Flags Carousel */}
              {selectedPlatforms.length > 0 && baseRedFlags.length > 0 && (
                <div className="w-full max-w-2xl bg-red-500/5 border border-red-500/20 rounded-2xl p-5 overflow-hidden">
                  <h3 className="text-red-400 text-xs font-bold flex items-center gap-2 mb-4 uppercase tracking-widest">
                    <AlertTriangle className="w-4 h-4" /> {t.carousel.title}
                  </h3>
                  
                  <div 
                    className="relative w-full overflow-hidden"
                    style={{
                      maskImage: 'linear-gradient(to right, transparent, black 15%, black 85%, transparent)',
                      WebkitMaskImage: 'linear-gradient(to right, transparent, black 15%, black 85%, transparent)'
                    }}
                  >
                    <div 
                      ref={scrollRef}
                      onMouseEnter={() => setIsHovered(true)}
                      onMouseLeave={() => {
                        setIsHovered(false);
                        handleMouseUpOrLeave();
                      }}
                      onMouseDown={handleMouseDown}
                      onMouseMove={handleMouseMove}
                      onMouseUp={handleMouseUpOrLeave}
                      className={`flex gap-4 overflow-x-auto py-2 no-scrollbar select-none transition-colors ${
                        isDragging ? 'cursor-grabbing' : 'cursor-grab'
                      }`}
                      style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}
                    >
                      {/* Render base block twice */}
                      {[...baseRedFlags, ...baseRedFlags].map((flag, index) => (
                        <div 
                          key={index} 
                          className="bg-black/40 p-4 rounded-xl border border-red-500/10 hover:border-emerald-500/50 hover:bg-zinc-900 transition-all w-[280px] flex-shrink-0 flex flex-col justify-between"
                        >
                          <span className="text-red-300 font-bold text-[10px] uppercase mb-2 flex items-center gap-1.5 tracking-wider pointer-events-none">
                            {(() => { const Icon = getPlatformIcon(flag.platform); return Icon ? <Icon className="w-3 h-3" /> : null; })()}
                            {flag.platform}
                          </span>
                          <p className="text-zinc-300 text-xs leading-relaxed italic pointer-events-none">
                            "{flag.text}"
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {/* Quick Actions */}
              <div className="w-full max-w-2xl">
                <p className="text-zinc-600 text-[10px] font-bold uppercase tracking-widest mb-3 text-center">
                  {t.quickActions.label}
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {(selectedPlatforms.length >= 2 ? t.quickActions.comparison : t.quickActions.items).map((text, i) => (
                    <button
                      key={i}
                      onClick={() => askNinja(text)}
                      className="flex items-center gap-3 p-4 bg-zinc-900 border border-zinc-800 hover:border-emerald-500/50 hover:bg-emerald-500/5 rounded-xl transition-all text-left group shadow-lg"
                    >
                      <div className="bg-zinc-800 text-emerald-500 p-2 rounded-lg group-hover:scale-110 group-hover:bg-emerald-500 group-hover:text-black transition-all duration-300">
                        {QUICK_ACTION_ICONS[i]}
                      </div>
                      <span className="text-sm text-zinc-300 group-hover:text-emerald-400 transition-colors">
                        {text}
                      </span>
                    </button>
                  ))}
                </div>
              </div>

            </div>
          )}

          {messages.map((msg, i) => {
            const isLastMessage = i === messages.length - 1;

            if (msg.role === 'system') {
              return (
                <div 
                  key={i} 
                  ref={isLastMessage ? lastMessageRef : null}
                  className="flex justify-center my-4 animate-in fade-in slide-in-from-bottom-2 duration-300 scroll-mt-20"
                >
                  <span className="bg-zinc-800/80 text-emerald-400 text-xs px-3 py-1.5 rounded-full font-mono border border-emerald-500/20 shadow-[0_0_10px_rgba(16,185,129,0.1)]">
                    {msg.content}
                  </span>
                </div>
              );
            }

            // Normal chat message
            return (
              <div 
                key={i} 
                ref={isLastMessage ? lastMessageRef : null}
                className={`flex gap-4 animate-in fade-in slide-in-from-bottom-2 duration-300 scroll-mt-20 ${
                  msg.role === 'user' ? 'justify-end' : 'justify-start'
                }`}
              >
                {/* Assistant Avatar */}
                {msg.role === 'assistant' && (
                  <div className="w-8 h-8 rounded-lg bg-emerald-500 flex-shrink-0 flex items-center justify-center">
                    <Scale className="w-4 h-4 text-black" />
                  </div>
                )}
                
                {/* Message Bubble */}
                <div className={`max-w-[85%] rounded-2xl p-4 ${
                  msg.role === 'user' ? 'bg-zinc-800' : 'bg-zinc-900 border border-zinc-800'
                }`}>
                  <div className="prose prose-invert prose-sm max-w-none break-words">
                    <ReactMarkdown 
                      remarkPlugins={[remarkGfm]} 
                      components={{
                        p: ({children}) => <p className="mb-4 last:mb-0">{children}</p>,
                        blockquote: ({children}) => (
                          <blockquote className="border-l-4 border-emerald-500 bg-zinc-800/50 p-3 my-4 italic">
                            {children}
                          </blockquote>
                        ),
                        table: ({children}) => (
                          <div className="overflow-x-auto my-6">
                            <table className="min-w-full border border-zinc-700 rounded-lg text-left">
                              {children}
                            </table>
                          </div>
                        ),
                        thead: ({children}) => <thead className="bg-zinc-800 text-emerald-500 font-bold">{children}</thead>,
                        th: ({children}) => <th className="px-4 py-2 border-b border-zinc-700">{children}</th>,
                        td: ({children}) => <td className="px-4 py-2 border-b border-zinc-800">{children}</td>,
                        a: ({node, ...props}) => (
                          <a 
                            {...props} 
                            target="_blank" 
                            rel="noopener noreferrer" 
                            className="text-blue-400 hover:text-blue-300 underline underline-offset-2 transition-colors"
                          />
                        ),
                      }}
                    >
                      {msg.content}
                    </ReactMarkdown>
                  </div>
                  
                  {/* Assistant Footer */}
                  {msg.role === 'assistant' && (
                     <div className="mt-4 pt-3 border-t border-zinc-800 flex gap-3 text-[10px] text-zinc-500 uppercase tracking-tighter">
                        <span className="flex items-center gap-1"><CheckCircle2 className="w-3 h-3 text-emerald-500"/> {t.chat.ragActive}</span>
                        <span className="flex items-center gap-1"><AlertTriangle className="w-3 h-3 text-amber-500"/> {t.chat.notLegalAdvice}</span>
                     </div>
                  )}
                </div>

                {/* User Avatar */}
                {msg.role === 'user' && (
                  <div className="w-8 h-8 rounded-lg bg-zinc-700 flex-shrink-0 flex items-center justify-center text-zinc-400">
                    <User className="w-4 h-4" />
                  </div>
                )}
              </div>
            );
          })}

          {loading && (
            <div className="flex gap-4 animate-in fade-in slide-in-from-bottom-2 duration-300 justify-start">
              {/* Loading Assistant Avatar */}
              <div className="w-8 h-8 rounded-lg bg-emerald-500/20 flex-shrink-0 flex items-center justify-center">
                <div className="w-4 h-4 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
              </div>
              
              {/* Status Bubble */}
              <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-4 flex items-center">
                <span className="text-xs font-mono text-emerald-500 uppercase tracking-widest animate-pulse">
                  {statusMessage}
                </span>
              </div>
            </div>
          )}
          <div ref={chatEndRef} />
        </div>

        {/* Input Fixed Box */}
        <div className="sticky bottom-0 bg-[#09090b] pb-4 px-2">
          
          {/* Quick Platform Selector */}
          {showQuickSelector && (
            <div  ref={menuRef} className="absolute bottom-20 left-4 bg-zinc-900 border border-zinc-700 p-4 rounded-2xl shadow-2xl animate-in fade-in zoom-in duration-200 z-50 flex flex-col gap-3 min-w-[220px]">
              
              <div className="flex items-center justify-between px-1">
                <p className="text-[10px] text-zinc-500 font-bold uppercase tracking-widest">{t.platforms.label}</p>
                {/* Toggle All Button (inside dropdown) */}
                <button 
                  onClick={toggleAll}
                  className="text-[10px] bg-zinc-800 hover:bg-zinc-700 text-zinc-300 px-2 py-1 rounded-md transition-colors"
                >
                  {isAllSelected ? t.platforms.unselectAll : t.platforms.selectAll}
                </button>
              </div>

              <div className="flex flex-col gap-1">
                {allPlatforms.map((p) => {
                  const Icon = getPlatformIcon(p);
                  return (
                    <button
                      key={p}
                      onClick={() => togglePlatform(p)}
                      className={`flex items-center justify-between px-3 py-2 rounded-lg text-sm transition-colors ${
                        selectedPlatforms.includes(p) 
                        ? 'bg-emerald-500/10 text-emerald-500' 
                        : 'text-zinc-400 hover:bg-zinc-800'
                      }`}
                    >
                      <span className="flex items-center gap-2">
                        {Icon && <Icon className="w-4 h-4" />}
                        {p}
                      </span>
                      {selectedPlatforms.includes(p) && <CheckCircle2 className="w-3 h-3" />}
                    </button>
                  );
                })}
              </div>

              {/* Divider */}
              <div className="h-px bg-zinc-800 my-1" />

              {/* Auto-detection Toggle */}
              <div className="flex items-center justify-between px-1">
                <div className="flex flex-col">
                  <span className="text-xs font-medium text-zinc-300">{t.autoDetection.label}</span>
                  <span className="text-[9px] text-zinc-500 uppercase">{t.autoDetection.subtitle}</span>
                </div>
                <button
                  onClick={() => setAutoDetect(!autoDetect)}
                  className={`w-10 h-5 rounded-full relative transition-colors duration-200 ${
                    autoDetect ? 'bg-emerald-500' : 'bg-zinc-700'
                  }`}
                >
                  <div className={`absolute top-1 w-3 h-3 bg-white rounded-full transition-all duration-200 ${
                    autoDetect ? 'left-6' : 'left-1'
                  }`} />
                </button>
              </div>
            </div>
          )}

          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-2 flex items-center focus-within:border-emerald-500 transition-all shadow-2xl relative">
            
            {/* Platform Selector Button */}
            <button 
              onClick={() => setShowQuickSelector(!showQuickSelector)}
              className={`p-3 rounded-xl transition-colors ${showQuickSelector ? 'bg-emerald-500 text-black' : 'text-zinc-500 hover:bg-zinc-800'}`}
              title={t.platforms.switchPlatforms}
            >
              <Scale className="w-5 h-5" />
            </button>

            <input 
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if(e.key === 'Enter') {
                  askNinja();
                  setShowQuickSelector(false);
                }
              }}
              placeholder={`${t.chat.placeholder} ${selectedPlatforms.length > 0 ? selectedPlatforms.join(', ') : t.chat.placeholderEmpty}...`}
              className="flex-1 bg-transparent border-none focus:ring-0 p-4 text-base outline-none"
            />

            <div className="relative flex items-center gap-2">
            
            {/* Mode Dropdown Menu */}
            {isModeMenuOpen && (
              <>
                {/* Backdrop */}
                <div 
                  className="fixed inset-0 z-40"
                  onClick={() => setIsModeMenuOpen(false)}
                />
                
                {/* Menu Box */}
                <div className="absolute bottom-full right-0 mb-3 w-72 bg-zinc-900 border border-zinc-800 rounded-2xl shadow-2xl py-2 z-50 overflow-hidden flex flex-col animate-in fade-in slide-in-from-bottom-2 duration-200">
                  <div className="px-4 py-3 text-xs font-semibold text-zinc-400 border-b border-zinc-800/50 mb-1">
                    {t.modes.label}
                  </div>
                  
                  {MODES.map((mode) => (
                    <button
                      key={mode.id}
                      type="button"
                      onClick={() => {
                        setResponseMode(mode.id as 'explanation' | 'legal');
                        setIsModeMenuOpen(false);
                      }}
                      className="flex items-center justify-between px-4 py-3 hover:bg-zinc-800/60 transition-colors text-left group"
                    >
                      <div className="flex flex-col pr-4">
                        <span className={`text-sm font-medium ${responseMode === mode.id ? 'text-white' : 'text-zinc-300 group-hover:text-white'}`}>
                          {mode.title}
                        </span>
                        <span className="text-xs text-zinc-500 mt-0.5">
                          {mode.description}
                        </span>
                      </div>
                      
                      {/* Selected Check Icon */}
                      {responseMode === mode.id && (
                        <div className="bg-emerald-500 text-zinc-950 rounded-full p-0.5 flex-shrink-0">
                          <Check className="w-3 h-3" strokeWidth={3} />
                        </div>
                      )}
                    </button>
                  ))}
                </div>
              </>
            )}

            {/* Mode Trigger Button */}
            <button
              type="button"
              onClick={() => setIsModeMenuOpen(!isModeMenuOpen)}
              className="flex items-center gap-2 px-4 py-2.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-full text-sm font-medium transition-colors"
            >
              {responseMode === 'explanation' ? t.modes.explanation.title : t.modes.legal.title}
              <ChevronDown className={`w-4 h-4 text-zinc-500 transition-transform ${isModeMenuOpen ? 'rotate-180' : ''}`} />
            </button>

            {/* Send Button */}
            
            <button 
              onClick={() => {
                askNinja();
                setShowQuickSelector(false);
              }}
              disabled={loading}
              className="bg-emerald-500 text-black p-4 rounded-xl hover:bg-emerald-400 transition-colors disabled:opacity-50"
            >
              {loading ? (
                <div className="animate-spin h-5 w-5 border-2 border-black border-t-transparent rounded-full" />
              ) : (
                <Send className="w-5 h-5" />
              )}
            </button>
          </div>
          </div>
          
          <p className="text-[10px] text-center text-zinc-600 mt-4 uppercase tracking-[0.2em]">
            {t.footer.version} • {selectedPlatforms.length} {t.platforms.activePlatforms}
          </p>
        </div>
      </div>
    </main>
  );
}