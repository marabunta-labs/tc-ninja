export default {
  header: {
    subtitle: "I translate complex legal terms into plain language. Ask me what they really do with your data.",
  },
  platforms: {
    all: "All",
    none: "None",
    selectAll: "Select all",
    unselectAll: "Unselect all",
    label: "Platforms",
    switchPlatforms: "Switch platforms",
    activePlatforms: "active platforms",
  },
  carousel: {
    title: "Did you know...",
  },
  quickActions: {
    label: "Common queries",
    items: [
      "Who really owns the photos and videos I upload?",
      "Can they delete my account without explanation?",
      "Tell me the most abusive clause they currently have.",
      "How do they use my private data to train their AI?",
    ],
    comparison: [
      "Which one is the most aggressive with my data?",
      "Who protects my privacy the best among these?",
      "Compare how they use my data to train AI.",
      "Which one makes it hardest to delete my account?",
    ],
  },
  chat: {
    placeholder: "Ask about",
    placeholderEmpty: "select a platform",
    noWeapon: "⚠️ No weapon selected: Choose at least one platform.",
    connectionError: "❌ Connection error with Ninja. Please try again in a few seconds.",
    overloaded: "⚠️ *The model is taking longer than expected. It may be overloaded right now.*",
    analyzingIntent: "Analyzing intent...",
    consultingNinjas: "Consulting legal ninjas...",
    ragActive: "RAG active",
    notLegalAdvice: "Not legal advice",
  },
  modes: {
    label: "Response mode",
    explanation: {
      title: "Simple",
      description: "Colloquial and direct translation for everyday use",
    },
    legal: {
      title: "Technical",
      description: "Strict legal language for professionals",
    },
  },
  autoDetection: {
    label: "Auto-detection",
    subtitle: "Smart AI",
  },
  footer: {
    version: "T&C Ninja v1.0",
    createdBy: "Created by",
  },
} as const;
