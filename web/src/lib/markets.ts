export interface MarketConfig {
  id: string;
  name: string;
  flag: string;
  language_code: string;
  voice: string;
  font_family: string;
}

export const MARKET_CONFIGS: Record<string, MarketConfig> = {
  japan: {
    id: "japan",
    name: "Japan",
    flag: "🇯🇵",
    language_code: "ja",
    voice: "Aoede",
    font_family: "Noto Sans JP",
  },
  germany: {
    id: "germany",
    name: "Germany",
    flag: "🇩🇪",
    language_code: "de",
    voice: "Charon",
    font_family: "Inter",
  },
  india: {
    id: "india",
    name: "India",
    flag: "🇮🇳",
    language_code: "hi",
    voice: "Kore",
    font_family: "Noto Sans Devanagari",
  },
  english: {
    id: "english",
    name: "English (UK/US)",
    flag: "🇬🇧",
    language_code: "en",
    voice: "Puck",
    font_family: "Arial",
  },
};

export const ALL_MARKETS = Object.keys(MARKET_CONFIGS);

export function getMarket(id: string): MarketConfig | undefined {
  return MARKET_CONFIGS[id.toLowerCase()];
}
