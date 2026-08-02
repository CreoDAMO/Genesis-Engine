/** Neon terminal palette — use these hex values inside SVG attributes and Recharts fills.
 *  CSS custom properties (var(--neon-green) etc.) only work in style props, not SVG presentation attributes.
 */
export const NEON = {
  green:  '#00ff88',
  amber:  '#ffaa00',
  red:    '#ff3366',
  cyan:   '#00d4ff',
  purple: '#9f55ff',
  orange: '#ff7a35',   // primary brand
} as const;

export type NeonKey = keyof typeof NEON;

export function sharpeColor(sharpe: number): string {
  if (sharpe > 1.5) return NEON.green;
  if (sharpe > 0.5) return NEON.amber;
  return NEON.red;
}
