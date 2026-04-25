import React from "react";
import type { ComponentType } from "react";
import { PLATFORMS } from "./index";

export function getPlatformIcon(id: string): ComponentType<{ className?: string }> | undefined {
  const platform = PLATFORMS.find((p) => p.id === id);
  if (!platform?.icon) return undefined;

  const { elements, ...svgProps } = platform.icon;

  return function PlatformIcon({ className }: { className?: string }) {
    return (
      <svg
        {...(svgProps as React.SVGProps<SVGSVGElement>)}
        className={className}
      >
        {elements.map(({ tag, ...attrs }, i) =>
          React.createElement(tag as React.ElementType, { key: i, ...attrs })
        )}
      </svg>
    );
  };
}

export const PLATFORM_ICONS: Record<string, ComponentType<{ className?: string }>> =
  Object.fromEntries(
    PLATFORMS
      .filter((p) => p.icon != null)
      .map((p) => [p.id, getPlatformIcon(p.id)!])
  );

