/* Chart colours for evilcharts configs, matched to MIRA's tokens.
 * Each is { light, dark }; evilcharts switches on [data-theme='dark'].
 * `signal` is the brand green — use it for the series that matters most. */

const pair = (light: string, dark: string) => ({ light: [light], dark: [dark] });

export const CHART_COLORS = {
  signal: pair('#2c7a1c', '#a6e36b'),
  neutral: pair('#8a8f8a', '#5c615c'),
  blue: pair('#2f6fd6', '#5b8def'),
  amber: pair('#9a6a0b', '#e0a93a'),
  violet: pair('#7a55c4', '#9b7ad6'),
  red: pair('#b3382f', '#e5645a'),
} as const;
