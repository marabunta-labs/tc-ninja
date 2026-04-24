"use client";
import { useState, useRef, useEffect } from 'react';
import { Shield, Send, MessageSquare, AlertTriangle, Scale, CheckCircle2, User,  Search, Zap, Eye, Trash2, Camera, ChevronLeft, ChevronRight } from 'lucide-react';
import { Check, ChevronDown } from 'lucide-react';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// Ampliamos los datos para que el carrusel tenga "chicha"
const RED_FLAGS: Record<string, string[]> = {
  'Instagram': [
    "Te exigen una licencia mundial y libre de regalías para usar cualquier foto que subas.",
    "Pueden eliminar tu cuenta y tus fotos en cualquier momento sin previo aviso.",
    "Rastrean tu actividad en otras webs si usas su navegador integrado.",
    "Tus metadatos (ubicación, hora de la foto) se guardan y analizan."
  ],
  'TikTok': [
    "Recopilan tus patrones de pulsación de teclas y el ritmo con el que escribes.",
    "Pueden compartir tus datos personales con empresas de su grupo en China.",
    "Analizan los objetos y rostros que aparecen en tus vídeos para perfilado.",
    "Guardan tu ubicación precisa mediante GPS y redes Wi-Fi cercanas."
  ],
  'X-Twitter': [
    "Tienen derecho a usar tus tuits para entrenar modelos de Inteligencia Artificial.",
    "Eres el único responsable legal si un tuit tuyo infringe la ley.",
    "Rastrean los enlaces en los que haces clic dentro de la plataforma.",
    "Pueden suspender tu cuenta si consideran que tu comportamiento es 'tóxico'."
  ]
};

const QUICK_ACTIONS = [
  { icon: <Camera className="w-4 h-4" />, text: "¿Quién es el dueño real de las fotos y vídeos que subo?" },
  { icon: <Trash2 className="w-4 h-4" />, text: "¿Me pueden borrar la cuenta sin dar explicaciones?" },
  { icon: <Zap className="w-4 h-4" />, text: "Dime la cláusula más abusiva que tienen actualmente." },
  { icon: <Eye className="w-4 h-4" />, text: "¿Cómo usan mis datos privados para entrenar su IA?" }
];

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
  const [responseMode, setResponseMode] = useState<'explicacion' | 'legal'>('explicacion');
  const [isModeMenuOpen, setIsModeMenuOpen] = useState(false);

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

const getBaseFlags = () => {
    const platforms = selectedPlatforms;
    if (platforms.length === 0) return [];
    
    const flagsByPlatform = platforms.map(p => RED_FLAGS[p]);
    const maxLength = Math.max(...flagsByPlatform.map(f => f.length));
    let interleaved: { platform: string; text: string }[] = [];

    for (let i = 0; i < maxLength; i++) {
      platforms.forEach(p => {
        if (RED_FLAGS[p][i]) {
          interleaved.push({ platform: p, text: RED_FLAGS[p][i] });
        }
      });
    }

    // EL TRUCO PARA EVITAR EL "LÍMITE": 
    // Aseguramos que el bloque base tenga al menos 4 tarjetas para que siempre sea 
    // más ancho que la pantalla. Si tiene menos, lo rellenamos consigo mismo.
    let base = [...interleaved];
    while (base.length > 0 && base.length < 4) {
      base = [...base, ...interleaved];
    }
    return base;
  };

  const baseRedFlags = getBaseFlags();

  // 2. MOTOR DE MOVIMIENTO Y ARRASTRE "DELTA"
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
      el.scrollLeft += 0.5; // Velocidad constante
      
      // Control de bucle para el auto-play
      if (el.scrollLeft >= el.scrollWidth / 2) {
        el.scrollLeft -= el.scrollWidth / 2;
      }
      animationId = requestAnimationFrame(step);
    };
    
    animationId = requestAnimationFrame(step);
    return () => cancelAnimationFrame(animationId);
  }, [isDragging, isHovered, baseRedFlags]);

  // Arrastre Manual sin límites
  const handleMouseDown = (e: React.MouseEvent) => {
    setIsDragging(true);
    setStartX(e.pageX); // Solo guardamos dónde tienes el ratón
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging || !scrollRef.current) return;
    e.preventDefault();
    
    const el = scrollRef.current;
    const x = e.pageX;
    const walk = (startX - x) * 1.5; // Distancia que has movido el ratón desde el ÚLTIMO frame
    
    let newScrollLeft = el.scrollLeft + walk;

    // MAGIA: Hacemos el teletransporte matemático antes de que el navegador lo bloquee en el 0
    if (newScrollLeft <= 0) {
      newScrollLeft += el.scrollWidth / 2;
    } else if (newScrollLeft >= el.scrollWidth / 2) {
      newScrollLeft -= el.scrollWidth / 2;
    }

    el.scrollLeft = newScrollLeft;
    setStartX(x); // Actualizamos el anclaje para que el próximo movimiento sea fluido
  };

  const handleMouseUpOrLeave = () => {
    setIsDragging(false);
  };
  
  // Referencia para hacer scroll automático al último mensaje
  const chatEndRef = useRef<HTMLDivElement>(null);
  const lastMessageRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  // Lógica inteligente de scroll corregida
  useEffect(() => {
    if (loading) {
      chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
    } else if (messages.length > 0) {
      // Solo hacemos scroll al inicio del mensaje del bot una vez
      lastMessageRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [messages.length, loading]);

  // Función para alternar selección
  const togglePlatform = (p: string) => {
    setSelectedPlatforms(prev => 
      prev.includes(p) 
      ? prev.filter(x => x !== p) 
      : [...prev, p]
    );
  };

  const askNinja = async (manualQuestion?: string) => {
    // Si viene un texto por el parámetro lo usamos, si no, usamos lo que hay en el input
    const currentQuestion = manualQuestion || question;

    if (!currentQuestion.trim()) return;

    if (!autoDetect && selectedPlatforms.length === 0) {
      setMessages(prev => [...prev, { role: 'system', content: '⚠️ Ninja sin armas: Selecciona al menos una red social.' }]);
      setQuestion('');
      return;
    }
    
    // Limpiamos el input
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
      

      const response = await fetch('http://localhost:8000/ask', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          platforms: activePlatforms,
          messages: [...chatHistoryForBackend, newUserMessage],
          mode: responseMode // 👈 ENVIAMOS EL MODO AQUÍ
        })
      });

      if (!response.body) throw new Error('No se recibió el stream de datos');

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let done = false;
      let text = '';
      
      // 🚩 NUEVO: Bandera para saber si es el primer fragmento de texto
      let isFirstChunk = true; 

      while (!done) {
        const { value, done: doneReading } = await reader.read();
        done = doneReading;
        
        if (value) {
          // Decodificamos el nuevo texto
          text += decoder.decode(value, { stream: true });
          
          if (isFirstChunk) {
            // 🚩 JUSTO CUANDO LLEGA LA PRIMERA LETRA:
            // 1. Apagamos la animación de carga
            setStatusMessage('');
            setLoading(false);
            
            // 2. Creamos la burbuja por primera vez YA CON TEXTO
            setMessages(prev => [...prev, { role: 'assistant', content: text }]);
            
            // 3. Bajamos la bandera para que los siguientes fragmentos solo actualicen
            isFirstChunk = false;
          } else {
            // A partir de la segunda letra, solo actualizamos el último mensaje
            setMessages(prev => {
              const newMessages = [...prev];
              newMessages[newMessages.length - 1].content = text;
              return newMessages;
            });
          }
        }
      }
      
      // Seguridad: por si la conexión se cierra antes de enviar ni una sola letra
      if (isFirstChunk) {
        setStatusMessage('');
        setLoading(false);
      }
      
    } catch (err) {
      setMessages(prev => [...prev, { role: 'system', content: '❌ Error en la conexión con el Ninja.' }]);
      setStatusMessage('');
      setLoading(false);
    }
  };

  const MODES = [
    { 
      id: 'explicacion', 
      title: 'Sencillo', 
      description: 'Traducción coloquial y directa para el día a día' 
    },
    { 
      id: 'legal', 
      title: 'Técnico', 
      description: 'Lenguaje jurídico estricto para profesionales' 
    }
  ];

  return (
    <main className="min-h-screen bg-[#09090b] text-zinc-100 p-4 md:p-12 font-sans">
      <div className="max-w-4xl mx-auto flex flex-col min-h-[80vh]">
        
        {/* Header Section */}
        <header className="flex flex-col items-center mb-8 text-center">
          <div className="bg-emerald-500/10 p-3 rounded-2xl mb-4">
            <Shield className="w-10 h-10 text-emerald-500" />
          </div>
          <h1 className="text-3xl font-black tracking-tight mb-2">T&C NINJA</h1>
          <div className="text-center space-y-2">
            <p className="text-zinc-400 text-sm max-w-md mx-auto mb-6">
              Traduzco los términos legales complejos al lenguaje claro. Pregúntame qué hacen realmente con tus datos.
            </p>
          </div>
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

        <div className="flex-1 space-y-6 mb-8 min-h-[400px]">
          
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center mt-10 space-y-10 animate-in fade-in zoom-in duration-500 px-4">
              
              {/* Sabías que... (CARRUSEL NINJA DEFINITIVO) */}
              {selectedPlatforms.length > 0 && baseRedFlags.length > 0 && (
                <div className="w-full max-w-2xl bg-red-500/5 border border-red-500/20 rounded-2xl p-5 overflow-hidden">
                  <h3 className="text-red-400 text-xs font-bold flex items-center gap-2 mb-4 uppercase tracking-widest">
                    <AlertTriangle className="w-4 h-4" /> Sabías que...
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
                      {/* Renderizamos el bloque exacto 2 veces */}
                      {[...baseRedFlags, ...baseRedFlags].map((flag, index) => (
                        <div 
                          key={index} 
                          className="bg-black/40 p-4 rounded-xl border border-red-500/10 hover:border-emerald-500/50 hover:bg-zinc-900 transition-all w-[280px] flex-shrink-0 flex flex-col justify-between"
                        >
                          <span className="text-red-300 font-bold text-[10px] uppercase mb-2 block tracking-wider pointer-events-none">
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

              {/* Acciones Rápidas */}
              <div className="w-full max-w-2xl">
                <p className="text-zinc-600 text-[10px] font-bold uppercase tracking-widest mb-3 text-center">
                  Consultas habituales
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {QUICK_ACTIONS.map((action, i) => (
                    <button
                      key={i}
                      onClick={() => askNinja(action.text)}
                      className="flex items-center gap-3 p-4 bg-zinc-900 border border-zinc-800 hover:border-emerald-500/50 hover:bg-emerald-500/5 rounded-xl transition-all text-left group shadow-lg"
                    >
                      <div className="bg-zinc-800 text-emerald-500 p-2 rounded-lg group-hover:scale-110 group-hover:bg-emerald-500 group-hover:text-black transition-all duration-300">
                        {action.icon}
                      </div>
                      <span className="text-sm text-zinc-300 group-hover:text-emerald-400 transition-colors">
                        {action.text}
                      </span>
                    </button>
                  ))}
                </div>
              </div>

            </div>
          )}

          {messages.map((msg, i) => {
            const isLastMessage = i === messages.length - 1; // Comprobamos si es el último

            if (msg.role === 'system') {
              return (
                <div 
                  key={i} 
                  ref={isLastMessage ? lastMessageRef : null} // Asignamos el ref
                  className="flex justify-center my-4 animate-in fade-in slide-in-from-bottom-2 duration-300 scroll-mt-20"
                >
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
                ref={isLastMessage ? lastMessageRef : null} // Asignamos el ref
                className={`flex gap-4 animate-in fade-in slide-in-from-bottom-2 duration-300 scroll-mt-20 ${
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

          {loading && (
            <div className="flex gap-4 animate-in fade-in slide-in-from-bottom-2 duration-300 justify-start">
              {/* Avatar de carga del Assistant */}
              <div className="w-8 h-8 rounded-lg bg-emerald-500/20 flex-shrink-0 flex items-center justify-center">
                <div className="w-4 h-4 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
              </div>
              
              {/* Burbuja de estado */}
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

            {/* Este bloque va dentro de tu contenedor del input de texto, al lado del botón de Enviar */}
          <div className="relative flex items-center gap-2">
            
            {/* MENÚ DESPLEGABLE (Se muestra si isModeMenuOpen es true) */}
            {isModeMenuOpen && (
              <>
                {/* Capa invisible para cerrar el menú al hacer clic fuera */}
                <div 
                  className="fixed inset-0 z-40"
                  onClick={() => setIsModeMenuOpen(false)}
                />
                
                {/* Caja del Menú (Aparece hacia arriba: bottom-full y mb-3) */}
                <div className="absolute bottom-full right-0 mb-3 w-72 bg-zinc-900 border border-zinc-800 rounded-2xl shadow-2xl py-2 z-50 overflow-hidden flex flex-col animate-in fade-in slide-in-from-bottom-2 duration-200">
                  <div className="px-4 py-3 text-xs font-semibold text-zinc-400 border-b border-zinc-800/50 mb-1">
                    Modo de respuesta
                  </div>
                  
                  {MODES.map((mode) => (
                    <button
                      key={mode.id}
                      type="button"
                      onClick={() => {
                        setResponseMode(mode.id as 'explicacion' | 'legal');
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
                      
                      {/* Icono de Check redondo para la opción seleccionada */}
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

            {/* BOTÓN DISPARADOR (El que se ve siempre en la barra) */}
            <button
              type="button"
              onClick={() => setIsModeMenuOpen(!isModeMenuOpen)}
              className="flex items-center gap-2 px-4 py-2.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-full text-sm font-medium transition-colors"
            >
              {responseMode === 'explicacion' ? 'Sencillo' : 'Técnico'}
              <ChevronDown className={`w-4 h-4 text-zinc-500 transition-transform ${isModeMenuOpen ? 'rotate-180' : ''}`} />
            </button>

            {/* TU BOTÓN DE ENVIAR ACTUAL IRÍA AQUÍ AL LADO */}
            {/* <button type="submit" ... > <Send /> </button> */}
            
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
            Ninja Legal v2.0 • {selectedPlatforms.length} redes activas
          </p>
        </div>
      </div>
    </main>
  );
}