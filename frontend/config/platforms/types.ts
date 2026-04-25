export interface IconElement {
  tag: string;
  [key: string]: string | number;
}

export interface IconConfig {
  viewBox: string;
  fill?: string;
  stroke?: string;
  strokeWidth?: number;
  strokeLinecap?: string;
  strokeLinejoin?: string;
  elements: IconElement[];
}

export interface PlatformConfig {
  id: string;
  color: string;
  scrapeUrls: Record<string, string[]>;
  icon: IconConfig;
  redFlags: Record<string, string[]>;
}
