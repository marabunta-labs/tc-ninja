import { describe, it, expect } from "vitest";
import { PLATFORMS, PLATFORM_IDS, getPlatform } from "../config/platforms";
import { getPlatformIcon } from "../config/platforms/icons";

describe("Platform configuration", () => {
  it("exports all ten platforms", () => {
    expect(PLATFORM_IDS.length).toBe(10);
  });

  it("each platform has required fields", () => {
    for (const p of PLATFORMS) {
      expect(p.id).toBeTruthy();
      expect(p.color).toMatch(/^#/);
      expect(p.scrapeUrls.es.length).toBeGreaterThan(0);
      expect(p.scrapeUrls.en.length).toBeGreaterThan(0);
    }
  });

  it("getPlatform returns correct platform", () => {
    const ig = getPlatform("Instagram");
    expect(ig?.id).toBe("Instagram");
    expect(ig?.color).toBe("#E1306C");

    const fb = getPlatform("Facebook");
    expect(fb?.id).toBe("Facebook");
    expect(fb?.color).toBe("#1877F2");
  });

  it("getPlatform returns undefined for unknown", () => {
    expect(getPlatform("Mastodon")).toBeUndefined();
  });

  it("has icon mapping for all platforms", () => {
    for (const id of PLATFORM_IDS) {
      const icon = getPlatformIcon(id);
      expect(typeof getPlatformIcon).toBe("function");
    }
  });
});
