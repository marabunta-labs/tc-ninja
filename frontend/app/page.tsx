"use client";
import { useState, useRef, useEffect } from 'react';
import { Shield, Send, MessageSquare, AlertTriangle, Scale, CheckCircle2, User } from 'lucide-react';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';

export default function Home() {
  const [question, setQuestion] = useState('');
  const [platform, setPlatform] = useState('Instagram');
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState<{ role: 'user' | 'assistant', content: string }[]>([]);
  
  // Referencia para hacer scroll automático al último mensaje
  const chatEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const askNinja = async () => {
    if (!question.trim()) return;
    
    const newUserMessage = { role: 'user' as const, content: question };
    const updatedMessages = [...messages, newUserMessage];
    
    setMessages(updatedMessages);
    setQuestion('');
    setLoading(true);

    try {
      const res = await axios.post('http://localhost:8000/ask', {
        platform,
        messages: updatedMessages 
      });
      
      setMessages([...updatedMessages, { role: 'assistant', content: res.data.answer }]);
    } catch (err) {
      setMessages([...updatedMessages, { 
        role: 'assistant', 
        content: "❌ Error de conexión. Revisa que el backend y tu API Key estén activos." 
      }]);
    }
    setLoading(false);
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
          <div className="flex gap-2">
            {['Instagram', 'TikTok', 'X-Twitter'].map((p) => (
              <button 
                key={p}
                onClick={() => { setPlatform(p); setMessages([]); }}
                className={`text-xs py-1 px-3 rounded-full border transition-all ${
                  platform === p 
                  ? 'bg-emerald-500 border-emerald-500 text-black font-bold' 
                  : 'bg-zinc-900 border-zinc-800 text-zinc-500 hover:border-zinc-700'
                }`}
              >
                {p}
              </button>
            ))}
          </div>
        </header>

        {/* Chat History Area */}
        <div className="flex-1 space-y-6 mb-8 min-h-[400px]">
          {messages.length === 0 && (
            <div className="text-center py-20 border border-dashed border-zinc-800 rounded-3xl">
              <MessageSquare className="w-12 h-12 text-zinc-700 mx-auto mb-4" />
              <p className="text-zinc-500">Selecciona una plataforma y lanza tu primera duda legal.</p>
            </div>
          )}

          {messages.map((msg, i) => (
            <div 
              key={i} 
              className={`flex gap-4 animate-in fade-in slide-in-from-bottom-2 duration-300 ${
                msg.role === 'user' ? 'justify-end' : 'justify-start'
              }`}
            >
              {msg.role === 'assistant' && (
                <div className="w-8 h-8 rounded-lg bg-emerald-500 flex-shrink-0 flex items-center justify-center">
                  <Scale className="w-4 h-4 text-black" />
                </div>
              )}
              
              <div className={`max-w-[85%] rounded-2xl p-4 ${
                msg.role === 'user' ? 'bg-zinc-800' : 'bg-zinc-900 border border-zinc-800'
              }`}>
                <div className="prose prose-invert prose-sm max-w-none break-words">
                  <ReactMarkdown 
                    components={{
                      p: ({children}) => <p className="mb-4 last:mb-0">{children}</p>,
                      blockquote: ({children}) => (
                        <blockquote className="border-l-4 border-emerald-500 bg-zinc-800/50 p-3 my-4 italic">
                          {children}
                        </blockquote>
                      )
                    }}
                  >
                    {msg.content}
                  </ReactMarkdown>
                </div>
                {msg.role === 'assistant' && (
                   <div className="mt-4 pt-3 border-t border-zinc-800 flex gap-3 text-[10px] text-zinc-500 uppercase tracking-tighter">
                      <span className="flex items-center gap-1"><CheckCircle2 className="w-3 h-3 text-emerald-500"/> RAG activo</span>
                      <span className="flex items-center gap-1"><AlertTriangle className="w-3 h-3 text-amber-500"/> No es consejo legal</span>
                   </div>
                )}
              </div>

              {msg.role === 'user' && (
                <div className="w-8 h-8 rounded-lg bg-zinc-700 flex-shrink-0 flex items-center justify-center text-zinc-400">
                  <User className="w-4 h-4" />
                </div>
              )}
            </div>
          ))}
          <div ref={chatEndRef} />
        </div>

        {/* Input Fixed Box */}
        <div className="sticky bottom-0 bg-[#09090b] pb-4">
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-2 flex items-center focus-within:border-emerald-500 transition-all shadow-2xl">
            <input 
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && askNinja()}
              placeholder={`Preguntar a Ninja sobre ${platform}...`}
              className="flex-1 bg-transparent border-none focus:ring-0 p-4 text-base outline-none"
            />
            <button 
              onClick={askNinja}
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
            Protegiendo tus datos, un párrafo a la vez
          </p>
        </div>
      </div>
    </main>
  );
}