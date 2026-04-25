import en from "./en";
import es from "./es";
import sharedConfig from "../config/shared.json";

export const SUPPORTED_LANGUAGES = sharedConfig.languages as readonly string[];

// To add a new language:
// 1. Add the language code to shared.json → "languages" array
// 2. Create locales/<code>.ts with UI strings (copy en.ts as template)
// 3. Add the import and entry below (2 lines)
export type Locale = "es" | "en";

export type Translations = {
  header: { subtitle: string };
  platforms: {
    all: string;
    none: string;
    selectAll: string;
    unselectAll: string;
    label: string;
    switchPlatforms: string;
    activePlatforms: string;
  };
  carousel: { title: string };
  quickActions: { label: string; items: readonly string[]; comparison: readonly string[] };
  chat: {
    placeholder: string;
    placeholderEmpty: string;
    noWeapon: string;
    connectionError: string;
    overloaded: string;
    analyzingIntent: string;
    consultingNinjas: string;
    ragActive: string;
    notLegalAdvice: string;
  };
  modes: {
    label: string;
    explanation: { title: string; description: string };
    legal: { title: string; description: string };
  };
  autoDetection: { label: string; subtitle: string };
  footer: { version: string };
  redFlags: Record<string, readonly string[]>;
};

type BaseLocale = Omit<Translations, "redFlags">;

const dictionaries: Record<Locale, BaseLocale> = { en, es };

function buildRedFlags(locale: string): Record<string, readonly string[]> {
  return Object.fromEntries(
    sharedConfig.platforms.map((p) => [
      p.id,
      ((p.redFlags as Record<string, string[]>)[locale]) ?? [],
    ])
  );
}

export function getTranslations(locale: Locale): Translations {
  return {
    ...dictionaries[locale],
    redFlags: buildRedFlags(locale),
  };
}
