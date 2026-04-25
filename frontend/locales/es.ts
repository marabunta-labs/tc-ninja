export default {
  header: {
    subtitle: "Traduzco los términos legales complejos al lenguaje claro. Pregúntame qué hacen realmente con tus datos.",
  },
  platforms: {
    all: "Todas",
    none: "Ninguna",
    selectAll: "Marcar todas",
    unselectAll: "Quitar todas",
    label: "Plataformas",
    switchPlatforms: "Cambiar plataformas",
    activePlatforms: "redes activas",
  },
  carousel: {
    title: "Sabías que...",
  },
  quickActions: {
    label: "Consultas habituales",
    items: [
      "¿Quién es el dueño real de las fotos y vídeos que subo?",
      "¿Me pueden borrar la cuenta sin dar explicaciones?",
      "Dime la cláusula más abusiva que tienen actualmente.",
      "¿Cómo usan mis datos privados para entrenar su IA?",
    ],
    comparison: [
      "¿Cuál es la más agresiva con mis datos?",
      "¿Cuál protege mejor mi privacidad entre estas?",
      "Compara cómo usan mis datos para entrenar su IA.",
      "¿En cuál es más difícil eliminar la cuenta?",
    ],
  },
  chat: {
    placeholder: "Preguntar sobre",
    placeholderEmpty: "selecciona una red",
    noWeapon: "⚠️ Ninja sin armas: Selecciona al menos una red social.",
    connectionError: "❌ Error en la conexión con el Ninja. Por favor, inténtalo de nuevo en unos segundos.",
    overloaded: "⚠️ *El modelo está tardando más de lo esperado. Puede estar sobrecargado en este momento.*",
    analyzingIntent: "Analizando intención...",
    consultingNinjas: "Consultando a los ninjas legales...",
    ragActive: "RAG activo",
    notLegalAdvice: "No es consejo legal",
  },
  modes: {
    label: "Modo de respuesta",
    explanation: {
      title: "Sencillo",
      description: "Traducción coloquial y directa para el día a día",
    },
    legal: {
      title: "Técnico",
      description: "Lenguaje jurídico estricto para profesionales",
    },
  },
  autoDetection: {
    label: "Auto-detección",
    subtitle: "IA Inteligente",
  },
  footer: {
    version: "Ninja Legal v2.0",
  },
} as const;
