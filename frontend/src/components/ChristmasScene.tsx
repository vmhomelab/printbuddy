/**
 * Decorative winter scene for the Christmas theme style: a snowy village with
 * decorated houses and a Christmas tree along the bottom of the viewport, and
 * Santa's sleigh flying across the sky.  Purely decorative (aria-hidden,
 * pointer-events disabled); colours come from the --scene-* variables in
 * index.css so it adapts to light and dark mode.
 */

import { useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { findFreeSleighLane } from '../utils/christmasSleighLane';

const GROUND_Y = 340;

const HOUSES = [
  { x: 60, w: 120, h: 90, wall: '#8b2a2a' },
  { x: 230, w: 90, h: 112, wall: '#2f5d3a' },
  { x: 370, w: 140, h: 80, wall: '#2c4a6e' },
  { x: 580, w: 100, h: 100, wall: '#8a5a2b' },
  { x: 760, w: 130, h: 86, wall: '#8b2a2a' },
  { x: 940, w: 95, h: 106, wall: '#2f5d3a' },
  { x: 1350, w: 120, h: 90, wall: '#2c4a6e' },
  { x: 1500, w: 90, h: 80, wall: '#8a5a2b' },
];

const LIGHT_COLORS = ['#ef4444', '#facc15', '#22c55e', '#60a5fa'];

function House({ x, w, h, wall }: (typeof HOUSES)[number]) {
  const top = GROUND_Y - h;
  const roofPeak = top - w * 0.45;
  const mid = x + w / 2;
  // Fairy lights spaced evenly along both roof edges
  const lights = Array.from({ length: 9 }, (_, i) => {
    const t = i / 8;
    const onLeft = t <= 0.5;
    const k = onLeft ? t * 2 : (t - 0.5) * 2;
    const lx = onLeft ? x - 6 + (mid - x + 6) * k : mid + (x + w + 6 - mid) * k;
    const ly = onLeft ? top + (roofPeak - top) * k : roofPeak + (top - roofPeak) * k;
    return { lx, ly: ly + 7, color: LIGHT_COLORS[i % LIGHT_COLORS.length] };
  });
  const winW = w * 0.2;
  return (
    <g>
      {/* Chimney */}
      <rect x={x + w * 0.68} y={roofPeak + w * 0.08} width={w * 0.12} height={w * 0.3} className="scene-roof" />
      <rect x={x + w * 0.66} y={roofPeak + w * 0.06} width={w * 0.16} height={6} rx={3} className="scene-snow" />
      {/* Walls */}
      <rect x={x} y={top} width={w} height={h} fill={wall} className="scene-wall" />
      {/* Roof with snow cover */}
      <polygon points={`${x - 10},${top + 4} ${mid},${roofPeak} ${x + w + 10},${top + 4}`} className="scene-roof" />
      <polyline
        points={`${x - 10},${top + 2} ${mid},${roofPeak} ${x + w + 10},${top + 2}`}
        fill="none"
        strokeWidth={9}
        strokeLinejoin="round"
        strokeLinecap="round"
        style={{ stroke: 'var(--scene-snow)' }}
      />
      {lights.map((l, i) => (
        <circle key={i} cx={l.lx} cy={l.ly} r={3.2} fill={l.color} className="scene-light" style={{ animationDelay: `${(i % 4) * 0.4}s` }} />
      ))}
      {/* Glowing windows */}
      <g className="scene-window">
        <rect x={x + w * 0.14} y={top + h * 0.2} width={winW} height={winW} rx={2} />
        <rect x={x + w * 0.66} y={top + h * 0.2} width={winW} height={winW} rx={2} />
      </g>
      <g stroke={wall} strokeWidth={2}>
        <line x1={x + w * 0.14 + winW / 2} y1={top + h * 0.2} x2={x + w * 0.14 + winW / 2} y2={top + h * 0.2 + winW} />
        <line x1={x + w * 0.66 + winW / 2} y1={top + h * 0.2} x2={x + w * 0.66 + winW / 2} y2={top + h * 0.2 + winW} />
      </g>
      {/* Door with wreath */}
      <rect x={mid - w * 0.1} y={GROUND_Y - h * 0.45} width={w * 0.2} height={h * 0.45} rx={3} fill="#3b2416" />
      <circle cx={mid} cy={GROUND_Y - h * 0.3} r={w * 0.055} fill="none" stroke="#166534" strokeWidth={3.5} />
      <circle cx={mid} cy={GROUND_Y - h * 0.3 + w * 0.055} r={2.2} fill="#dc2626" />
    </g>
  );
}

function ChristmasTree({ x }: { x: number }) {
  const tiers = [
    { y: 300, w: 150, h: 70 },
    { y: 250, w: 118, h: 64 },
    { y: 202, w: 84, h: 58 },
  ];
  const baubles = [
    [-50, 292, '#dc2626'], [-12, 285, '#facc15'], [30, 294, '#3b82f6'], [58, 288, '#dc2626'],
    [-34, 242, '#3b82f6'], [6, 236, '#dc2626'], [36, 244, '#facc15'],
    [-18, 194, '#facc15'], [16, 190, '#dc2626'],
  ] as const;
  return (
    <g>
      <rect x={x - 10} y={GROUND_Y - 40} width={20} height={40} fill="#5b3a1e" />
      {tiers.map((t, i) => (
        <g key={i}>
          <polygon points={`${x - t.w / 2},${t.y} ${x},${t.y - t.h - 30} ${x + t.w / 2},${t.y}`} fill="#166534" className="scene-tree" />
          <path
            d={`M${x - t.w / 2} ${t.y} Q ${x - t.w / 4} ${t.y - 8}, ${x} ${t.y - 2} T ${x + t.w / 2} ${t.y}`}
            fill="none"
            strokeWidth={6}
            strokeLinecap="round"
            style={{ stroke: 'var(--scene-snow)' }}
          />
        </g>
      ))}
      {/* Golden garland */}
      <path
        d={`M${x - 58} 270 Q ${x} 290, ${x + 52} 262 M${x - 40} 220 Q ${x} 238, ${x + 38} 214`}
        fill="none"
        stroke="#eab308"
        strokeWidth={3}
        strokeDasharray="2 5"
        strokeLinecap="round"
      />
      {baubles.map(([dx, y, c], i) => (
        <circle key={i} cx={x + dx} cy={y} r={6} fill={c} className="scene-light" style={{ animationDelay: `${(i % 3) * 0.5}s` }} />
      ))}
      {/* Star */}
      <polygon
        transform={`translate(${x} 118)`}
        points="0,-18 5,-6 18,-6 8,2 12,15 0,7 -12,15 -8,2 -18,-6 -5,-6"
        fill="#facc15"
        className="scene-star"
      />
    </g>
  );
}

function Reindeer({ x, y, rudolph = false }: { x: number; y: number; rudolph?: boolean }) {
  return (
    <g transform={`translate(${x} ${y})`}>
      {/* Leaping legs: hind legs stretched back, front legs tucked */}
      <path
        d="M14 34 L5 42 L0 48 M19 35 L11 44 L6 49 M42 31 L51 37 L49 44 M39 33 L46 41 L42 46"
        stroke="#7c4a21"
        strokeWidth={3}
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <path d="M11 26 L3 21 L8 29 Z" fill="#f5ead6" />
      <ellipse cx={28} cy={29} rx={18} ry={8} fill="#a0703f" transform="rotate(-10 28 29)" />
      <ellipse cx={28} cy={33} rx={13} ry={3.5} fill="#ead9bb" transform="rotate(-10 28 33)" />
      <path d="M38 25 L47 11 L54 13 L45 30 Z" fill="#a0703f" />
      <ellipse cx={54} cy={11} rx={7} ry={4.5} fill="#a0703f" />
      <ellipse cx={49} cy={7} rx={2.5} ry={1.4} fill="#7c4a21" transform="rotate(-30 49 7)" />
      <path
        d="M50 8 C 46 2, 45 -4, 47 -9 M47 -1 L42 -3 M48 -5 L44 -9 M53 7 C 54 0, 56 -4, 59 -8 M55 -2 L60 -3"
        stroke="#4b3621"
        strokeWidth={2}
        strokeLinecap="round"
        fill="none"
      />
      {/* Harness with golden studs */}
      <path d="M41 19 L37 37" stroke="#d42a3c" strokeWidth={4} strokeLinecap="round" />
      <circle cx={40} cy={23} r={1.1} fill="#facc15" />
      <circle cx={39} cy={28} r={1.1} fill="#facc15" />
      <circle cx={38} cy={33} r={1.1} fill="#facc15" />
      <circle
        cx={61}
        cy={12}
        r={rudolph ? 2.8 : 1.7}
        fill={rudolph ? '#ef4444' : '#3b2416'}
        className={rudolph ? 'scene-light' : undefined}
      />
    </g>
  );
}

/** Santa in his sleigh, pulled by three leaping reindeer, flying to the right. */
function SantaSleigh() {
  return (
    <svg viewBox="0 -4 330 92" className="christmas-sleigh" aria-hidden="true">
      {/* Golden reins from Santa's hand to each harness */}
      <path
        d="M58 12 C 80 30, 120 46, 152 46 C 175 47, 196 51, 217 50 C 240 49, 262 46, 283 44"
        stroke="#eab308"
        strokeWidth={1.4}
        fill="none"
      />
      {/* Little Christmas tree riding along at the back */}
      <polygon points="4,36 15,10 26,36" fill="#166534" />
      <polygon points="7,24 15,4 23,24" fill="#15803d" />
      <circle cx={11} cy={28} r={1.8} fill="#dc2626" />
      <circle cx={20} cy={22} r={1.8} fill="#facc15" />
      <circle cx={14} cy={16} r={1.6} fill="#3b82f6" />
      <polygon transform="translate(15 3)" points="0,-5 1.5,-1.5 5,-1.5 2.2,0.8 3.2,4.5 0,2.2 -3.2,4.5 -2.2,0.8 -5,-1.5 -1.5,-1.5" fill="#facc15" />
      {/* Santa, waving */}
      <ellipse cx={38} cy={38} rx={12} ry={13} fill="#d42a3c" />
      <rect x={27} y={39} width={22} height={4} fill="#1f2937" />
      <rect x={36} y={38.5} width={5} height={5} fill="none" stroke="#facc15" strokeWidth={1.2} />
      <path d="M46 31 L57 14" stroke="#d42a3c" strokeWidth={5} strokeLinecap="round" />
      <circle cx={58} cy={12} r={3.2} fill="#facc15" />
      <circle cx={40} cy={19} r={7} fill="#f3c9a5" />
      <path d="M33 19 Q 40 37, 47 19 Z" fill="#f8fafc" />
      <path d="M34 14 L47 14 Q 44 2, 33 5 Q 29 7, 28 11 Z" fill="#d42a3c" />
      <circle cx={28} cy={11} r={2.6} fill="#f8fafc" />
      <rect x={32} y={12} width={17} height={4} rx={2} fill="#f8fafc" />
      {/* Gift sack with presents */}
      <rect x={58} y={26} width={8} height={9} fill="#a855f7" />
      <rect x={65} y={24} width={8} height={11} fill="#3b82f6" />
      <line x1={69} y1={24} x2={69} y2={35} stroke="#facc15" strokeWidth={1.5} />
      <ellipse cx={67} cy={42} rx={13} ry={9} fill="#991b1b" />
      {/* Sleigh */}
      <path
        d="M6 34 L22 34 C 24 44, 30 48, 40 48 L80 48 C 88 48, 92 44, 94 38 L100 40 C 98 54, 90 62, 78 62 L30 62 C 14 62, 6 52, 6 34 Z"
        fill="#d42a3c"
      />
      <path d="M22 34 C 24 44, 30 48, 40 48 L80 48 C 88 48, 92 44, 94 38" stroke="#facc15" strokeWidth={2.5} fill="none" />
      <circle cx={20} cy={54} r={1.6} fill="#fecaca" />
      <circle cx={46} cy={56} r={1.6} fill="#fecaca" />
      <circle cx={70} cy={55} r={1.6} fill="#fecaca" />
      {/* Lantern on the front */}
      <path d="M95 39 L95 30" stroke="#78350f" strokeWidth={1.4} />
      <rect x={92} y={24} width={6} height={7} rx={1} fill="#fde68a" stroke="#b45309" strokeWidth={1} className="scene-light" />
      {/* Runner */}
      <path
        d="M10 74 L92 74 C 104 74, 108 66, 104 60 C 101 56, 97 58, 98 62 M28 62 L26 74 M76 62 L78 74"
        stroke="#a16207"
        strokeWidth={3}
        strokeLinecap="round"
        fill="none"
      />
      {/* Reindeer team, Rudolph leading */}
      <Reindeer x={112} y={22} />
      <Reindeer x={177} y={26} />
      <Reindeer x={243} y={20} rudolph />
    </svg>
  );
}

export function ChristmasScene() {
  const { pathname } = useLocation();
  const trackRef = useRef<HTMLDivElement>(null);
  const villageRef = useRef<SVGSVGElement>(null);

  // Keep the sleigh in a lane that doesn't overlap page content.  Re-checked
  // before every flight (it is off-screen then), after navigation once the
  // page has rendered, and on resize.  Lane changes glide (see index.css).
  useEffect(() => {
    const track = trackRef.current;
    const village = villageRef.current;
    if (!track || !village) return;

    const place = () => {
      // The upper third of the village is open sky above the rooftops
      const villageRect = village.getBoundingClientRect();
      const floor = villageRect.top + villageRect.height * 0.3;
      const top = findFreeSleighLane(track.offsetHeight, floor);
      track.style.visibility = top === null ? 'hidden' : '';
      if (top !== null) track.style.top = `${top}px`;
    };

    // Pages fetch their data after mounting, so look again once it has arrived
    const timers = [300, 1500, 3500, 7000].map((ms) => window.setTimeout(place, ms));
    let resizeTimer = 0;
    const onResize = () => {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(place, 250);
    };
    track.addEventListener('animationiteration', place);
    window.addEventListener('resize', onResize);
    return () => {
      timers.forEach(window.clearTimeout);
      window.clearTimeout(resizeTimer);
      track.removeEventListener('animationiteration', place);
      window.removeEventListener('resize', onResize);
    };
  }, [pathname]);

  return (
    <>
      <div className="christmas-scene" aria-hidden="true">
        <div className="christmas-moon" />
        <svg ref={villageRef} viewBox="0 0 1600 400" preserveAspectRatio="xMidYMax slice" className="christmas-village">
          <path d="M0 300 C 200 240, 400 262, 600 280 C 800 298, 1000 232, 1200 252 C 1400 272, 1500 240, 1600 255 L1600 400 L0 400 Z" className="scene-hill" />
          {/* Distant fir trees */}
          {[150, 520, 700, 1080, 1290, 1560].map((tx, i) => (
            <polygon key={i} points={`${tx - 16},${300} ${tx},${248 + (i % 2) * 10} ${tx + 16},${300}`} className="scene-far-tree" />
          ))}
          {HOUSES.map((h) => <House key={h.x} {...h} />)}
          <ChristmasTree x={1200} />
          <path d="M0 336 C 300 318, 600 350, 900 334 C 1200 320, 1400 346, 1600 330 L1600 400 L0 400 Z" className="scene-ground" />
        </svg>
      </div>
      {/* Separate fixed layer so the sleigh can animate across the full viewport width;
          its top is set by the lane finder above */}
      <div ref={trackRef} className="christmas-sleigh-track" aria-hidden="true">
        <SantaSleigh />
      </div>
    </>
  );
}
