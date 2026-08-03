import type { SVGProps } from 'react';

/**
 * Printer-side spool assignment icon.
 *
 * Based on the provided "insert into tray" mark, but drawn as a theme-aware
 * rounded line icon so it fits beside the existing Lucide-style Printbuddy
 * controls and inherits button colors via currentColor.
 */
export function AssignSpoolIcon({ className, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      <path
        d="M5 13.25v4.25A2.5 2.5 0 0 0 7.5 20h9A2.5 2.5 0 0 0 19 17.5v-8"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M5 17.5h14"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
      />
      <path
        d="M4.75 7.25c4.7-1.8 8.1-.55 10.25 3.55"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
      />
      <path
        d="M14.95 4v6.85H8.3"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
