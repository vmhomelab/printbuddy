/**
 * Decorations for the farm dashboards (Farm Command Center and TV mode) while
 * the Christmas theme style is active: a fir garland with fairy lights along
 * the top and Santa's workshop, where little printers on a conveyor belt
 * print trees and gifts, along the bottom.  Purely decorative (aria-hidden,
 * pointer-events disabled) and static apart from the chimney smoke, which
 * moves by transform so it never repaints the drawing.
 */

const GARLAND_TILE = 240;
const LIGHT_COLORS = ['#ef4444', '#facc15', '#22c55e', '#60a5fa', '#f97316'];

// Deterministic needle layout for one garland tile (no randomness between
// renders): short needles fanning out along the swag in two shades
const swagY = (t: number) => 16 + Math.sin(t * Math.PI) * 14;
const NEEDLES = Array.from({ length: 150 }, (_, i) => {
  const t = (i % 75) / 74;
  const x = t * GARLAND_TILE;
  const y = swagY(t) + (((i * 7) % 9) - 4);
  const angle = ((i * 53) % 150) - 75 + (i < 75 ? 180 : 0);
  const length = 7 + ((i * 11) % 6);
  const rad = (angle * Math.PI) / 180;
  return { x, y, x2: x + Math.cos(rad) * length, y2: y + Math.sin(rad) * length * 0.8, light: i % 4 === 0 };
});
const GARLAND_LIGHTS = [0.08, 0.24, 0.41, 0.59, 0.76, 0.92].map((t, i) => ({
  x: t * GARLAND_TILE,
  y: swagY(t) + 9,
  color: LIGHT_COLORS[i % LIGHT_COLORS.length],
}));

export function ChristmasGarland() {
  return (
    <svg className="christmas-garland" aria-hidden="true" preserveAspectRatio="none">
      <defs>
        <radialGradient id="christmas-garland-glow">
          <stop offset="0" stopColor="#fff7d6" stopOpacity="0.9" />
          <stop offset="1" stopColor="#fff7d6" stopOpacity="0" />
        </radialGradient>
        <pattern id="christmas-garland-tile" width={GARLAND_TILE} height={64} patternUnits="userSpaceOnUse">
          <path d={`M-10 16 Q ${GARLAND_TILE / 2} 44, ${GARLAND_TILE + 10} 16`} stroke="#0f3d22" strokeWidth={18} fill="none" strokeLinecap="round" />
          {NEEDLES.map((n, i) => (
            <line key={i} x1={n.x} y1={n.y} x2={n.x2} y2={n.y2} stroke={n.light ? '#2f8f55' : '#1b6b3c'} strokeWidth={2.4} strokeLinecap="round" />
          ))}
          {/* Pine cones */}
          <ellipse cx={GARLAND_TILE * 0.33} cy={swagY(0.33) + 10} rx={4.5} ry={7} fill="#7c4a21" />
          <ellipse cx={GARLAND_TILE * 0.67} cy={swagY(0.67) + 9} rx={4} ry={6.5} fill="#6b3f1c" />
          {/* Fairy lights with a soft halo */}
          {GARLAND_LIGHTS.map((l) => (
            <g key={l.x}>
              <circle cx={l.x} cy={l.y} r={9} fill="url(#christmas-garland-glow)" opacity={0.55} />
              <circle cx={l.x} cy={l.y} r={3.2} fill={l.color} />
            </g>
          ))}
        </pattern>
      </defs>
      <rect width="100%" height="64" fill="url(#christmas-garland-tile)" />
    </svg>
  );
}

function SnowRoof({ x, y, w, peak }: { x: number; y: number; w: number; peak: number }) {
  return (
    <>
      <polygon points={`${x - 10},${y} ${x + w / 2},${y - peak} ${x + w + 10},${y}`} fill="#3b2416" />
      <polyline
        points={`${x - 10},${y - 2} ${x + w / 2},${y - peak} ${x + w + 10},${y - 2}`}
        fill="none"
        stroke="#e8eef3"
        strokeWidth={8}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </>
  );
}

function LitWindow({ x, y, w, h, arched = false }: { x: number; y: number; w: number; h: number; arched?: boolean }) {
  const path = arched
    ? `M${x} ${y + h} L${x} ${y + w / 2} A ${w / 2} ${w / 2} 0 0 1 ${x + w} ${y + w / 2} L${x + w} ${y + h} Z`
    : `M${x} ${y} h${w} v${h} h${-w} Z`;
  return (
    <g>
      <path d={path} fill="#fbbf24" />
      <path d={path} fill="none" stroke="#4a2511" strokeWidth={3} />
      <line x1={x + w / 2} y1={y + (arched ? 2 : 0)} x2={x + w / 2} y2={y + h} stroke="#4a2511" strokeWidth={2} />
      <line x1={x} y1={y + h * 0.55} x2={x + w} y2={y + h * 0.55} stroke="#4a2511" strokeWidth={2} />
    </g>
  );
}

function Gift({ x, y, s, color, ribbon = '#facc15' }: { x: number; y: number; s: number; color: string; ribbon?: string }) {
  return (
    <g>
      <rect x={x} y={y} width={s} height={s} fill={color} />
      <rect x={x + s / 2 - 1.5} y={y} width={3} height={s} fill={ribbon} />
      <rect x={x} y={y + s / 2 - 1.5} width={s} height={3} fill={ribbon} />
    </g>
  );
}

function MiniPrinter({ x, y, item }: { x: number; y: number; item: 'tree' | 'gift' }) {
  return (
    <g>
      <rect x={x} y={y} width={34} height={36} rx={3} fill="#1f2937" stroke="#4b5563" strokeWidth={1.5} />
      <rect x={x + 4} y={y + 5} width={26} height={24} fill="#0f172a" />
      {item === 'tree' ? (
        <polygon points={`${x + 17},${y + 9} ${x + 9},${y + 27} ${x + 25},${y + 27}`} fill="#22c55e" />
      ) : (
        <Gift x={x + 10} y={y + 14} s={14} color="#dc2626" />
      )}
      <rect x={x + 4} y={y + 31} width={8} height={2} fill="#22c55e" />
    </g>
  );
}

function FirTree({ x, base, h, lights = true }: { x: number; base: number; h: number; lights?: boolean }) {
  const w = h * 0.55;
  return (
    <g>
      <rect x={x - 3} y={base - 8} width={6} height={8} fill="#4a2c17" />
      <polygon points={`${x - w / 2},${base - 6} ${x},${base - h} ${x + w / 2},${base - 6}`} fill="#14532d" />
      <polygon points={`${x - w / 2.6},${base - h * 0.45} ${x},${base - h} ${x + w / 2.6},${base - h * 0.45}`} fill="#166534" />
      {lights &&
        [0.3, 0.5, 0.7].map((t, i) => (
          <circle key={t} cx={x + (i % 2 ? w * 0.18 : -w * 0.15)} cy={base - h * t} r={2} fill="#fde68a" />
        ))}
    </g>
  );
}

export function ChristmasWorkshop() {
  const GROUND = 236;
  return (
    <div className="christmas-workshop" aria-hidden="true">
      {/* Chimney smoke: its own layer so the puffs move without repainting the scene */}
      <div className="christmas-workshop-smoke">
        <span />
        <span />
        <span />
      </div>
      <svg viewBox="0 0 1600 260">
        <defs>
          <linearGradient id="christmas-workshop-fade" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="var(--scene-hill)" stopOpacity="0" />
            <stop offset="1" stopColor="var(--scene-hill)" stopOpacity="0.9" />
          </linearGradient>
        </defs>
        <rect x={0} y={100} width={1600} height={160} fill="url(#christmas-workshop-fade)" />

        {/* Forest behind the workshop */}
        {[60, 140, 230, 1330, 1420, 1520].map((x, i) => (
          <FirTree key={x} x={x} base={GROUND} h={90 + (i % 3) * 18} />
        ))}

        {/* Small houses at the edges */}
        <g>
          <rect x={300} y={GROUND - 62} width={80} height={62} fill="#7f1d1d" />
          <SnowRoof x={300} y={GROUND - 60} w={80} peak={34} />
          <LitWindow x={326} y={GROUND - 46} w={26} h={26} />
        </g>
        <g>
          <rect x={1220} y={GROUND - 70} width={92} height={70} fill="#7f1d1d" />
          <SnowRoof x={1220} y={GROUND - 68} w={92} peak={38} />
          <LitWindow x={1250} y={GROUND - 52} w={30} h={30} arched />
          <line x1={1300} y1={GROUND - 106} x2={1300} y2={GROUND - 150} stroke="#d1d5db" strokeWidth={2} />
          <path d={`M1301 ${GROUND - 150} h30 l-6 10 l6 10 h-30 Z`} fill="#b91c1c" />
          <Gift x={1308} y={GROUND - 146} s={10} color="#b91c1c" />
        </g>

        {/* Conveyor wing with printers printing trees and gifts */}
        <g>
          <rect x={420} y={GROUND - 92} width={250} height={92} fill="#6b1d1d" />
          <rect x={420} y={GROUND - 100} width={250} height={10} fill="#e8eef3" rx={4} />
          <rect x={432} y={GROUND - 78} width={226} height={50} fill="#1c1917" />
          <MiniPrinter x={446} y={GROUND - 74} item="tree" />
          <MiniPrinter x={526} y={GROUND - 74} item="gift" />
          <MiniPrinter x={606} y={GROUND - 74} item="tree" />
          <rect x={420} y={GROUND - 26} width={330} height={8} fill="#374151" />
          {[440, 480, 520, 560, 600, 640, 680, 720].map((x) => (
            <circle key={x} cx={x} cy={GROUND - 18} r={3.5} fill="#6b7280" />
          ))}
          <Gift x={680} y={GROUND - 42} s={16} color="#dc2626" />
          <Gift x={706} y={GROUND - 38} s={12} color="#16a34a" ribbon="#fde68a" />
          <Gift x={726} y={GROUND - 44} s={18} color="#b91c1c" />
        </g>

        {/* Main workshop with wreath and arched windows */}
        <g>
          <rect x={770} y={GROUND - 118} width={250} height={118} fill="#7f1d1d" />
          {[0, 1, 2, 3, 4, 5].map((row) => (
            <line key={row} x1={770} y1={GROUND - 100 + row * 18} x2={1020} y2={GROUND - 100 + row * 18} stroke="#6b1717" strokeWidth={1.5} />
          ))}
          <SnowRoof x={770} y={GROUND - 116} w={250} peak={64} />
          <rect x={950} y={GROUND - 192} width={22} height={40} fill="#57534e" />
          <rect x={946} y={GROUND - 196} width={30} height={7} rx={3} fill="#e8eef3" />
          <circle cx={895} cy={GROUND - 148} r={14} fill="none" stroke="#166534" strokeWidth={7} />
          <circle cx={895} cy={GROUND - 148} r={14} fill="none" stroke="#eab308" strokeWidth={1.5} strokeDasharray="2 5" />
          <path d={`M889 ${GROUND - 134} l6 -5 l6 5 Z`} fill="#dc2626" />
          <LitWindow x={810} y={GROUND - 92} w={52} h={70} arched />
          <LitWindow x={928} y={GROUND - 92} w={52} h={70} arched />
          <Gift x={822} y={GROUND - 42} s={14} color="#dc2626" />
          <Gift x={840} y={GROUND - 38} s={10} color="#16a34a" />
          <Gift x={942} y={GROUND - 42} s={14} color="#16a34a" ribbon="#fde68a" />
          <Gift x={958} y={GROUND - 36} s={10} color="#dc2626" />
          <rect x={878} y={GROUND - 50} width={34} height={50} rx={3} fill="#3b2416" />
        </g>

        {/* Right wing */}
        <g>
          <rect x={1030} y={GROUND - 84} width={170} height={84} fill="#6b1d1d" />
          <rect x={1030} y={GROUND - 92} width={170} height={10} fill="#e8eef3" rx={4} />
          <LitWindow x={1052} y={GROUND - 66} w={34} h={40} />
          <LitWindow x={1110} y={GROUND - 66} w={34} h={40} />
          <Gift x={1160} y={GROUND - 22} s={18} color="#dc2626" />
        </g>

        <FirTree x={1210} base={GROUND} h={70} />
        <FirTree x={400} base={GROUND} h={64} />

        <path d={`M0 ${GROUND - 6} C 300 ${GROUND - 14}, 600 ${GROUND + 2}, 900 ${GROUND - 8} C 1200 ${GROUND - 16}, 1400 ${GROUND}, 1600 ${GROUND - 10} L1600 260 L0 260 Z`} fill="var(--scene-ground)" />
      </svg>
    </div>
  );
}
