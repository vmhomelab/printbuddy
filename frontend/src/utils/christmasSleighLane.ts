/**
 * Finds a horizontal lane for the Christmas sleigh where it does not overlap
 * any visible page content.  The sleigh crosses the full viewport width, so a
 * lane is free only if no obstacle overlaps it vertically.
 *
 * Two passes, lowest lane first (just above the village rooftops):
 * 1. a lane clear of everything: text, controls, media and cards
 * 2. a lane where the sleigh only passes behind large opaque cards (it flies
 *    behind the content, so cards hide it but no text sits on top of it);
 *    small opaque elements such as icon circles or badges count as content
 * Returns null when neither exists; the caller then hides the sleigh.
 */

const CONTROL_TAGS = new Set(['BUTTON', 'INPUT', 'SELECT', 'TEXTAREA', 'IMG', 'svg', 'CANVAS', 'VIDEO']);
const MIN_TOP = 56; // keep clear of the fairy lights and page headers
const STEP = 8;
const PADDING = 14; // room for the bobbing animation plus some breathing space
const MIN_CARD_WIDTH = 300;

interface Band {
  top: number;
  bottom: number;
}

function isOpaque(style: CSSStyleDeclaration): boolean {
  if (style.backgroundImage && style.backgroundImage !== 'none') return true;
  const match = style.backgroundColor.match(/rgba?\(([^)]+)\)/);
  if (!match) return false;
  const parts = match[1].split(/[\s,/]+/).filter(Boolean);
  const alpha = parts.length > 3 ? parseFloat(parts[3]) : 1;
  return alpha >= 0.5;
}

function hasOwnText(el: Element): boolean {
  for (const node of el.childNodes) {
    if (node.nodeType === Node.TEXT_NODE && node.textContent?.trim()) return true;
  }
  return false;
}

export function findFreeSleighLane(sleighHeight: number, floor: number): number | null {
  const viewportHeight = window.innerHeight;
  const root = document.querySelector('main') ?? document.getElementById('root');
  if (!root) return null;

  const opaqueCache = new Map<Element, boolean>();
  const opaque = (el: Element) => {
    let value = opaqueCache.get(el);
    if (value === undefined) {
      value = isOpaque(getComputedStyle(el));
      opaqueCache.set(el, value);
    }
    return value;
  };
  const isCard = (el: Element) => opaque(el) && el.getBoundingClientRect().width >= MIN_CARD_WIDTH;
  const insideCard = (el: Element) => {
    for (let p = el.parentElement; p && p !== root; p = p.parentElement) {
      if (isCard(p)) return true;
    }
    return false;
  };

  const everything: Band[] = [];
  const uncovered: Band[] = [];
  for (const el of root.querySelectorAll('*')) {
    if (el.closest('.christmas-scene, .christmas-sleigh-track, aside')) continue;
    // Only the outer <svg> counts; its children add nothing
    if (el instanceof SVGElement && el.tagName !== 'svg') continue;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0 || rect.bottom < 0 || rect.top > viewportHeight) continue;
    const isBox = opaque(el);
    const isContent =
      CONTROL_TAGS.has(el.tagName) || hasOwnText(el) || (isBox && rect.width < MIN_CARD_WIDTH);
    if (!isContent && !isBox) continue;
    if (getComputedStyle(el).visibility === 'hidden') continue;
    const band = { top: rect.top, bottom: rect.bottom };
    everything.push(band);
    if (isContent && !insideCard(el)) uncovered.push(band);
  }

  const search = (obstacles: Band[]) => {
    for (let top = floor - sleighHeight; top >= MIN_TOP; top -= STEP) {
      const laneTop = top - PADDING;
      const laneBottom = top + sleighHeight + PADDING;
      if (!obstacles.some((b) => b.bottom > laneTop && b.top < laneBottom)) return top;
    }
    return null;
  };

  return search(everything) ?? search(uncovered);
}
