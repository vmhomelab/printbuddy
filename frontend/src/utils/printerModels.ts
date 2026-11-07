export type PrinterModelOptionGroup = {
  label: string;
  options: Array<{ value: string; label: string }>;
};

export const PRINTER_MODEL_GROUPS: PrinterModelOptionGroup[] = [
  {
    label: 'Bambu Lab A1 Series',
    options: [
      { value: 'A1', label: 'A1' },
      { value: 'A1 F', label: 'A1 F' },
      { value: 'A1 Mini', label: 'A1 Mini' },
    ],
  },
  {
    label: 'Bambu Lab A2 Series',
    options: [
      { value: 'A2L', label: 'A2L' },
    ],
  },
  {
    label: 'Bambu Lab P Series',
    options: [
      { value: 'P1P', label: 'P1P' },
      { value: 'P1S', label: 'P1S' },
      { value: 'P2S', label: 'P2S' },
    ],
  },
  {
    label: 'Bambu Lab X Series',
    options: [
      { value: 'X1', label: 'X1' },
      { value: 'X1C', label: 'X1 Carbon' },
      { value: 'X1E', label: 'X1E' },
      { value: 'X2D', label: 'X2D' },
    ],
  },
  {
    label: 'Bambu Lab H Series',
    options: [
      { value: 'O1C', label: 'O1C' },
      { value: 'O1E', label: 'O1E' },
      { value: 'O1S', label: 'O1S' },
      { value: 'H2C', label: 'H2C' },
      { value: 'H2D', label: 'H2D' },
      { value: 'H2D Pro', label: 'H2D Pro' },
      { value: 'H2S', label: 'H2S' },
    ],
  },
  {
    label: 'Elegoo',
    options: [
      { value: 'Elegoo Neptune 3', label: 'Neptune 3' },
      { value: 'Elegoo Neptune 3 Pro', label: 'Neptune 3 Pro' },
      { value: 'Elegoo Neptune 3 Plus', label: 'Neptune 3 Plus' },
      { value: 'Elegoo Neptune 3 Max', label: 'Neptune 3 Max' },
      { value: 'Elegoo Neptune 4', label: 'Neptune 4' },
      { value: 'Elegoo Neptune 4 Pro', label: 'Neptune 4 Pro' },
      { value: 'Elegoo Neptune 4 Plus', label: 'Neptune 4 Plus' },
      { value: 'Elegoo Neptune 4 Max', label: 'Neptune 4 Max' },
      { value: 'Elegoo Centauri', label: 'Centauri' },
      { value: 'Elegoo Centauri Carbon', label: 'Centauri Carbon' },
    ],
  },
  {
    label: 'Voron',
    options: [
      { value: 'Voron V0.2', label: 'V0.2' },
      { value: 'Voron Trident', label: 'Trident' },
      { value: 'Voron 2.4', label: '2.4' },
      { value: 'Voron Switchwire', label: 'Switchwire' },
      { value: 'Voron Legacy', label: 'Legacy' },
    ],
  },
  {
    label: 'Creality Klipper',
    options: [
      { value: 'Creality Ender-3', label: 'Ender-3' },
      { value: 'Creality Ender-3 Pro', label: 'Ender-3 Pro' },
      { value: 'Creality Ender-3 V2', label: 'Ender-3 V2' },
      { value: 'Creality Ender-3 S1', label: 'Ender-3 S1' },
      { value: 'Creality Ender-5 Plus', label: 'Ender-5 Plus' },
      { value: 'Creality CR-10S Pro', label: 'CR-10S Pro' },
      { value: 'Creality CR-10S Pro V2', label: 'CR-10S Pro V2' },
      { value: 'Creality K1', label: 'K1' },
      { value: 'Creality K1C', label: 'K1C' },
      { value: 'Creality K2', label: 'K2' },
      { value: 'Creality K2 Pro', label: 'K2 Pro' },
      { value: 'Creality K2 Plus', label: 'K2 Plus' },
    ],
  },
  {
    label: 'Snapmaker Klipper',
    options: [
      { value: 'Snapmaker U1', label: 'U1' },
    ],
  },
  {
    label: 'Prusa',
    options: [
      { value: 'Prusa CORE One', label: 'CORE One' },
      { value: 'Prusa MK4S', label: 'MK4S' },
      { value: 'Prusa MK4', label: 'MK4' },
      { value: 'Prusa MK3.9S', label: 'MK3.9S' },
      { value: 'Prusa MK3.9', label: 'MK3.9' },
      { value: 'Prusa MK3.5S', label: 'MK3.5S' },
      { value: 'Prusa MK3.5', label: 'MK3.5' },
      { value: 'Prusa XL', label: 'XL' },
      { value: 'Prusa MINI+', label: 'MINI+' },
      { value: 'Prusa MK3S+', label: 'MK3S+' },
      { value: 'Prusa SL1S SPEED', label: 'SL1S SPEED' },
    ],
  },
  {
    label: 'Generic',
    options: [
      { value: 'Klipper', label: 'Klipper / Moonraker' },
      { value: 'PrusaLink', label: 'PrusaLink' },
      { value: 'Generic Klipper Printer', label: 'Generic Klipper Printer' },
      { value: 'Generic FDM Printer', label: 'Generic FDM Printer' },
    ],
  },
];

// SSDP model code -> display name lives in printerModel.ts (one table for the
// whole app); re-exported here for existing importers.
export { mapModelCode } from './printerModel';
