/**
 * Santa hat overlay for the Printbuddy brand image, shown while the
 * Christmas theme style is active.  Positions are percentages of the
 * wrapping image so the hat sits straight and centred on the printer icon
 * at any size:
 * - "logo": wide wordmark (icon occupies the left ~6–29% of the image)
 * - "icon": square icon (collapsed sidebar, login page)
 */
interface ChristmasHatProps {
  variant: 'logo' | 'icon';
}

const PLACEMENT = {
  logo: { left: '6.6%', top: '-20%', width: '22%' },
  icon: { left: '15%', top: '-42%', width: '70%' },
} as const;

export function ChristmasHat({ variant }: ChristmasHatProps) {
  return (
    <svg
      viewBox="0 0 100 90"
      aria-hidden="true"
      className="pointer-events-none absolute"
      style={{ ...PLACEMENT[variant], overflow: 'visible' }}
      data-testid="christmas-hat"
    >
      {/* Hat body: upright cone whose tip flops over to the right */}
      <path
        d="M14 68 C 20 42, 32 16, 54 9 C 70 4, 86 11, 91 27 C 84 23, 76 25, 72 31 C 77 43, 83 55, 86 68 Z"
        fill="#d42a3c"
      />
      <path
        d="M72 31 C 77 43, 83 55, 86 68 L 72 68 C 68 55, 67 43, 72 31 Z"
        fill="#a51d2d"
        opacity="0.7"
      />
      {/* Fur brim */}
      <rect x="4" y="62" width="92" height="20" rx="10" fill="#f8fafc" stroke="#cbd5e1" strokeWidth="1.5" />
      {/* Pompom */}
      <circle cx="91" cy="29" r="10" fill="#ffffff" stroke="#cbd5e1" strokeWidth="1.5" />
    </svg>
  );
}
