"use client";
import { useState } from 'react';
import { Shield, Send, MessageSquare, AlertTriangle, Scale, CheckCircle2 } from 'lucide-react';
import axios from 'axios';

export default function Home() {
  const [question, setQuestion] = useState('');
  const [platform, setPlatform] = useState('Instagram');
  const [answer, setAnswer] = useState('');
  const [loading, setLoading] = useState(false);

  const askNinja = async () => {
    if (!question.trim()) return;
    setLoading(true);
    try {
      const res = await axios.post('http://localhost:8000/ask', {
        platform,
        question
      });
      setAnswer(res.data.answer);
    } catch (err) {
      setAnswer("❌ El Ninja ha detectado un error. Asegúrate de que el backend esté corriendo.");
    }
    setLoading(false);
  };

  return (
    <main className="min-h-screen bg-[#09090b] text-zinc-100 p-4 md:p-12 font-sans">
      <div className="max-w-4xl mx-auto">
        
        {/* Header Section */}
        <header className="flex flex-col items-center mb-12 text-center">
          <div className="bg-emerald-500/10 p-3 rounded-2xl mb-4">
            <Shield className="w-12 h-12 text-emerald-500" />
          </div>
          <h1 className="text-4xl font-black tracking-tight mb-2">T&C NINJA</h1>
          <p className="text-zinc-400 max-w-md">
            Desvelando lo que aceptaste sin leer. Inteligencia artificial aplicada al derecho digital.
          </p>
        </header>

        {/* Platform Selector */}
        <div className="grid grid-cols-3 gap-3 mb-8">
          {['Instagram', 'TikTok', 'X-Twitter'].map((p) => (
            <button 
              key={p}
              onClick={() => { setPlatform(p); setAnswer(''); }}
              className={`py-3 px-4 rounded-xl border transition-all duration-200 font-medium ${
                platform === p 
                ? 'bg-emerald-500 border-emerald-500 text-black shadow-[0_0_20px_rgba(16,185,129,0.2)]' 
                : 'bg-zinc-900 border-zinc-800 text-zinc-400 hover:border-zinc-700'
              }`}
            >
              {p}
            </button>
          ))}
        </div>

        {/* Input Box */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-2 flex items-center mb-8 focus-within:border-emerald-500 transition-all">
          <input 
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && askNinja()}
            placeholder={`¿Qué quieres saber de ${platform}?`}
            className="flex-1 bg-transparent border-none focus:ring-0 p-4 text-lg outline-none"
          />
          <button 
            onClick={askNinja}
            disabled={loading}
            className="bg-emerald-500 text-black p-4 rounded-xl hover:bg-emerald-400 transition-colors disabled:opacity-50"
          >
            {loading ? <div className="animate-spin h-5 w-5 border-2 border-black border-t-transparent rounded-full" /> : <Send className="w-5 h-5" />}
          </button>
        </div>

        {/* Results Area */}
        {answer && (
          <div className="space-y-6 animate-in fade-in slide-in-from-top-4 duration-500">
            <div className="bg-zinc-900/50 border border-zinc-800 rounded-3xl p-8">
              <div className="flex items-center gap-3 mb-6">
                <div className="w-8 h-8 rounded-full bg-emerald-500 flex items-center justify-center">
                  <Scale className="w-4 h-4 text-black" />
                </div>
                <h3 className="text-emerald-500 font-bold uppercase tracking-widest text-sm">Dictamen del Ninja</h3>
              </div>
              
              <div className="prose prose-invert max-w-none text-zinc-300 leading-relaxed">
                {answer.split('\n').map((line, i) => (
                  <p key={i} className="mb-2">{line}</p>
                ))}
              </div>
              
              <div className="mt-8 pt-6 border-t border-zinc-800 flex flex-wrap gap-4">
                <div className="flex items-center gap-2 text-xs text-zinc-500">
                  <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                  Verificado por Gemini 3.1
                </div>
                <div className="flex items-center gap-2 text-xs text-zinc-500">
                  <AlertTriangle className="w-4 h-4 text-amber-500" />
                  No es asesoría legal oficial
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}