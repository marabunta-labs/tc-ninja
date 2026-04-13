"use client";
import { useState, useRef, useEffect } from 'react';
import { Shield, Send, MessageSquare, AlertTriangle, Scale, CheckCircle2, User } from 'lucide-react';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export default function Home() {
  const [statusMessage, setStatusMessage] = useState(''); // Mensaje de "Cambiando contexto..."
  const [question, setQuestion] = useState('');
  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>(['Instagram']);
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState<{ role: 'user' | 'assistant' | 'system', content: string }[]>([]);
  // Lista maestra de plataformas
  const allPlatforms = ['Instagram', 'TikTok', 'X-Twitter'];
  const [showQuickSelector, setShowQuickSelector] = useState(false);
  const [autoDetect, setAutoDetect] = useState(true);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
  const handleClickOutside = (event: MouseEvent) => {
    // Si el menú está abierto y el clic NO está dentro del menú, lo cerramos
    if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
      setShowQuickSelector(false);
    }
  };

  document.addEventListener("mousedown", handleClickOutside);
  return () => {
    document.removeEventListener("mousedown", handleClickOutside);
  };
}, [showQuickSelector]);
  
  // Comprobamos si están todas seleccionadas
  const isAllSelected = selectedPlatforms.length === allPlatforms.length;

  const toggleAll = () => {
    if (isAllSelected) {
      setSelectedPlatforms([]); // Si están todas, las vaciamos (Ninguna)
    } else {
      setSelectedPlatforms(allPlatforms); // Si falta alguna, las marcamos todas
    }
  };
  
  // Referencia para hacer scroll automático al último mensaje
  const chatEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Función para alternar selección
  const togglePlatform = (p: string) => {
    setSelectedPlatforms(prev => 
      prev.includes(p) 
      ? prev.filter(x => x !== p) 
      : [...prev, p]
    );
  };

  const askNinja = async () => {
    if (!question.trim()) return;

    if (!autoDetect && selectedPlatforms.length === 0) {
      setMessages(prev => [...prev, { 
        role: 'system', 
        content: '⚠️ Ninja sin armas: Selecciona al menos una red social para que pueda analizar sus términos.' 
      }]);
      setQuestion('');
      return;
    }
    
    const currentQuestion = question;
    setQuestion(''); 
    
    const newUserMessage = { role: 'user' as const, content: currentQuestion };
    setMessages(prev => [...prev, newUserMessage]);
    setLoading(true);
    
    let activePlatforms = selectedPlatforms;

    try {
      // 2. SOLO ejecutamos la detección si autoDetect está activado
      if (autoDetect) {
        setStatusMessage('Analizando intención...'); 
        const detectRes = await axios.post('http://localhost:8000/detect-context', {
          message: currentQuestion,
          current_platforms: selectedPlatforms
        });

        if (detectRes.data.message) {
          activePlatforms = detectRes.data.platforms;
          setSelectedPlatforms(activePlatforms);
          setMessages(prev => [...prev, { role: 'system', content: detectRes.data.message }]);
        }
      }

      setStatusMessage('Consultando a los ninjas legales...');

      const chatHistoryForBackend = messages.filter(m => m.role !== 'system');
      const askRes = await axios.post('http://localhost:8000/ask', {
        platforms: activePlatforms,
        messages: [...chatHistoryForBackend, newUserMessage]
      });

      setMessages(prev => [...prev, { role: 'assistant', content: askRes.data.answer }]);
      
    } catch (err) {
      setMessages(prev => [...prev, { role: 'system', content: '❌ Error en la conexión.' }]);
    } finally {
      setStatusMessage('');
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-[#09090b] text-zinc-100 p-4 md:p-12 font-sans">
      <div className="max-w-4xl mx-auto flex flex-col min-h-[80vh]">
        
        {/* Header Section */}
        <header className="flex flex-col items-center mb-8 text-center">
          <div className="bg-emerald-500/10 p-3 rounded-2xl mb-4">
            <Shield className="w-10 h-10 text-emerald-500" />
          </div>
          <h1 className="text-3xl font-black tracking-tight mb-2">T&C NINJA</h1>
          <div className="flex gap-2 flex-wrap justify-center">
            
            {/* NUEVO BOTÓN: Todas / Ninguna */}
            <button
              onClick={toggleAll}
              className={`py-2 px-4 rounded-xl border transition-all duration-300 font-bold tracking-wide ${
                isAllSelected 
                ? 'bg-zinc-200 text-black border-zinc-200 shadow-[0_0_15px_rgba(228,228,231,0.3)] scale-105' 
                : 'bg-zinc-900 text-zinc-400 border-zinc-700 hover:border-zinc-500 hover:text-zinc-200'
              }`}
            >
              {isAllSelected ? 'Ninguna' : 'Todas'}
            </button>

            {/* Divisor visual opcional */}
            <div className="w-px bg-zinc-800 mx-1"></div>

            {/* Tus botones de redes sociales */}
            {allPlatforms.map((p) => (
              <button 
                key={p}
                onClick={() => togglePlatform(p)}
                className={`py-2 px-4 rounded-xl border transition-all duration-300 ${
                  selectedPlatforms.includes(p) 
                  ? 'bg-emerald-500 text-black border-emerald-500 shadow-lg scale-105' 
                  : 'bg-zinc-900 text-zinc-500 border-zinc-800 opacity-60 hover:opacity-100'
                }`}
              >
                {p}
              </button>
            ))}
          </div>
        </header>

        {/* Status Message dinámico */}
        {loading && (
          <div className="flex items-center justify-center gap-2 mb-4 animate-pulse">
            <div className="w-2 h-2 bg-emerald-500 rounded-full animate-bounce" />
            <span className="text-xs font-mono text-emerald-500 uppercase tracking-widest">
              {statusMessage}
            </span>
          </div>
        )}

        {/* Chat History Area */}
        <div className="flex-1 space-y-6 mb-8 min-h-[400px]">
          {messages.length === 0 && (
            <div className="text-center py-20 border border-dashed border-zinc-800 rounded-3xl">
              <MessageSquare className="w-12 h-12 text-zinc-700 mx-auto mb-4" />
              <p className="text-zinc-500">Selecciona una plataforma y lanza tu primera duda legal.</p>
            </div>
          )}

          {messages.map((msg, i) => {
            // 1. EVALUAMOS SI ES UN MENSAJE DE SISTEMA (CAMBIO DE CONTEXTO)
            if (msg.role === 'system') {
              return (
                <div key={i} className="flex justify-center my-4 animate-in fade-in slide-in-from-bottom-2 duration-300">
                  <span className="bg-zinc-800/80 text-emerald-400 text-xs px-3 py-1.5 rounded-full font-mono border border-emerald-500/20 shadow-[0_0_10px_rgba(16,185,129,0.1)]">
                    {msg.content}
                  </span>
                </div>
              );
            }

            // 2. SI NO ES DE SISTEMA, RENDERIZAMOS EL CHAT NORMAL
            return (
              <div 
                key={i} 
                className={`flex gap-4 animate-in fade-in slide-in-from-bottom-2 duration-300 ${
                  msg.role === 'user' ? 'justify-end' : 'justify-start'
                }`}
              >
                {/* Avatar del Assistant */}
                {msg.role === 'assistant' && (
                  <div className="w-8 h-8 rounded-lg bg-emerald-500 flex-shrink-0 flex items-center justify-center">
                    <Scale className="w-4 h-4 text-black" />
                  </div>
                )}
                
                {/* Burbuja del mensaje */}
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
                      }}
                    >
                      {msg.content}
                    </ReactMarkdown>
                  </div>
                  
                  {/* Footer del Assistant (Advertencias legales) */}
                  {msg.role === 'assistant' && (
                     <div className="mt-4 pt-3 border-t border-zinc-800 flex gap-3 text-[10px] text-zinc-500 uppercase tracking-tighter">
                        <span className="flex items-center gap-1"><CheckCircle2 className="w-3 h-3 text-emerald-500"/> RAG activo</span>
                        <span className="flex items-center gap-1"><AlertTriangle className="w-3 h-3 text-amber-500"/> No es consejo legal</span>
                     </div>
                  )}
                </div>

                {/* Avatar del User */}
                {msg.role === 'user' && (
                  <div className="w-8 h-8 rounded-lg bg-zinc-700 flex-shrink-0 flex items-center justify-center text-zinc-400">
                    <User className="w-4 h-4" />
                  </div>
                )}
              </div>
            );
          })}
          <div ref={chatEndRef} />
        </div>

        {/* Input Fixed Box */}
        {/* Input Fixed Box */}
        <div className="sticky bottom-0 bg-[#09090b] pb-4 px-2">
          
          {/* Menú rápido de plataformas (Aparece solo si showQuickSelector es true) */}
          {showQuickSelector && (
            <div  ref={menuRef} className="absolute bottom-20 left-4 bg-zinc-900 border border-zinc-700 p-4 rounded-2xl shadow-2xl animate-in fade-in zoom-in duration-200 z-50 flex flex-col gap-3 min-w-[220px]">
              
              <div className="flex items-center justify-between px-1">
                <p className="text-[10px] text-zinc-500 font-bold uppercase tracking-widest">Plataformas</p>
                {/* Botón Todas/Ninguna dentro del desplegable */}
                <button 
                  onClick={toggleAll}
                  className="text-[10px] bg-zinc-800 hover:bg-zinc-700 text-zinc-300 px-2 py-1 rounded-md transition-colors"
                >
                  {isAllSelected ? 'Quitar todas' : 'Marcar todas'}
                </button>
              </div>

              <div className="flex flex-col gap-1">
                {['Instagram', 'TikTok', 'X-Twitter'].map((p) => (
                  <button
                    key={p}
                    onClick={() => togglePlatform(p)}
                    className={`flex items-center justify-between px-3 py-2 rounded-lg text-sm transition-colors ${
                      selectedPlatforms.includes(p) 
                      ? 'bg-emerald-500/10 text-emerald-500' 
                      : 'text-zinc-400 hover:bg-zinc-800'
                    }`}
                  >
                    {p}
                    {selectedPlatforms.includes(p) && <CheckCircle2 className="w-3 h-3" />}
                  </button>
                ))}
              </div>

              {/* Separador */}
              <div className="h-px bg-zinc-800 my-1" />

              {/* Toggle de Auto-detección */}
              <div className="flex items-center justify-between px-1">
                <div className="flex flex-col">
                  <span className="text-xs font-medium text-zinc-300">Auto-detección</span>
                  <span className="text-[9px] text-zinc-500 uppercase">IA Inteligente</span>
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
            
            {/* BOTÓN DESPLEGABLE */}
            <button 
              onClick={() => setShowQuickSelector(!showQuickSelector)}
              className={`p-3 rounded-xl transition-colors ${showQuickSelector ? 'bg-emerald-500 text-black' : 'text-zinc-500 hover:bg-zinc-800'}`}
              title="Cambiar plataformas"
            >
              <Scale className="w-5 h-5" />
            </button>

            <input 
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if(e.key === 'Enter') {
                  askNinja();
                  setShowQuickSelector(false); // Cerramos el menú al enviar
                }
              }}
              placeholder={`Preguntar sobre ${selectedPlatforms.length > 0 ? selectedPlatforms.join(', ') : 'selecciona una red'}...`}
              className="flex-1 bg-transparent border-none focus:ring-0 p-4 text-base outline-none"
            />
            
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
          
          <p className="text-[10px] text-center text-zinc-600 mt-4 uppercase tracking-[0.2em]">
            Ninja Legal v2.0 • {selectedPlatforms.length} redes activas
          </p>
        </div>
      </div>
    </main>
  );
}