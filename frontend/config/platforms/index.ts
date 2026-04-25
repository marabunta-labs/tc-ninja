import sharedConfig from "../shared.json";
import type { PlatformConfig } from "./types";

export type { PlatformConfig };

export const PLATFORMS: PlatformConfig[] = sharedConfig.platforms;

export const PLATFORM_IDS = PLATFORMS.map((p) => p.id);

export function getPlatform(id: string): PlatformConfig | undefined {
  return PLATFORMS.find((p) => p.id === id);
}
