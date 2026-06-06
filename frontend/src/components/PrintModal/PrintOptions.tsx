import { useState } from 'react';
import { Settings, ChevronDown, ChevronUp } from 'lucide-react';
import type { PrintOptionsProps, PrintOptions as PrintOptionsType } from './types';

const PRINT_OPTIONS_CONFIG = [
  { key: 'bed_levelling', label: 'Bed Levelling', desc: 'Auto-level bed before print' },
  { key: 'flow_cali', label: 'Flow Calibration', desc: 'Calibrate extrusion flow' },
  { key: 'vibration_cali', label: 'Vibration Calibration', desc: 'Reduce ringing artifacts' },
  { key: 'layer_inspect', label: 'First Layer Inspection', desc: 'AI inspection of first layer' },
  { key: 'timelapse', label: 'Timelapse', desc: 'Record timelapse video' },
] as const;

/**
 * Print options toggle panel with collapsible UI.
 * Shows bed levelling, flow/vibration calibration, layer inspection, and timelapse options.
 */
export function PrintOptionsPanel({
  options,
  onChange,
  defaultExpanded = false,
  supportedOptions,
}: PrintOptionsProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const visibleOptions = PRINT_OPTIONS_CONFIG.filter(({ key }) => !supportedOptions || supportedOptions.includes(key));

  const handleToggle = (key: keyof PrintOptionsType) => {
    onChange({ ...options, [key]: !options[key] });
  };

  return (
    <div className="mb-4">
      <button
        type="button"
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center gap-2 text-sm text-bambu-gray hover:text-white transition-colors w-full"
      >
        <Settings className="w-4 h-4" />
        <span>Print Options</span>
        {isExpanded ? (
          <ChevronUp className="w-4 h-4 ml-auto" />
        ) : (
          <ChevronDown className="w-4 h-4 ml-auto" />
        )}
      </button>
      {isExpanded && (
        <div className="mt-2 bg-bambu-dark rounded-lg p-3 space-y-2">
          {visibleOptions.length === 0 ? (
            <p className="text-xs text-bambu-gray">No configurable print options for the selected printer.</p>
          ) : visibleOptions.map(({ key, label, desc }) => (
            <label key={key} className="flex items-center justify-between cursor-pointer group">
              <div>
                <span className="text-sm text-white">{label}</span>
                <p className="text-xs text-bambu-gray">{desc}</p>
              </div>
              <div
                className={`relative w-10 h-5 rounded-full transition-colors ${
                  options[key] ? 'bg-bambu-green' : 'bg-bambu-dark-tertiary'
                }`}
                onClick={() => handleToggle(key)}
              >
                <div
                  className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                    options[key] ? 'translate-x-5' : 'translate-x-0.5'
                  }`}
                />
              </div>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
