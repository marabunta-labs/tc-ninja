import { describe, it, expect } from "vitest";
import { getTranslations } from "../locales";
import { PLATFORM_IDS } from "../config/platforms";

describe("i18n translations", () => {
  it("returns English translations for 'en'", () => {
    const t = getTranslations("en");
    expect(t.header.subtitle).toContain("translate");
    expect(t.platforms.all).toBe("All");
    expect(t.modes.explanation.title).toBe("Simple");
  });

  it("returns Spanish translations for 'es'", () => {
    const t = getTranslations("es");
    expect(t.header.subtitle).toContain("Traduzco");
    expect(t.platforms.all).toBe("Todas");
    expect(t.modes.explanation.title).toBe("Sencillo");
  });

  it("has matching keys between en and es", () => {
    const en = getTranslations("en");
    const es = getTranslations("es");
    expect(Object.keys(en)).toEqual(Object.keys(es));
    expect(Object.keys(en.chat)).toEqual(Object.keys(es.chat));
    expect(Object.keys(en.modes)).toEqual(Object.keys(es.modes));
  });

  it("has quick action items in both locales", () => {
    const en = getTranslations("en");
    const es = getTranslations("es");
    expect(en.quickActions.items.length).toBe(4);
    expect(es.quickActions.items.length).toBe(4);
  });

  it("has red flags for all platforms", () => {
    const en = getTranslations("en");
    const es = getTranslations("es");
    for (const p of PLATFORM_IDS) {
      expect(en.redFlags[p].length).toBeGreaterThan(0);
      expect(es.redFlags[p].length).toBeGreaterThan(0);
    }
  });
});
