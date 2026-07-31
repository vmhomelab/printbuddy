import { describe, expect, it } from 'vitest';
import { resolveLoadedFilamentInfo } from '../../utils/amsHelpers';
import type { AMSTray, AMSUnit, InventorySpool, Printer, PrinterStatus, SpoolAssignment } from '../../api/client';

function spool(overrides: Partial<InventorySpool>): InventorySpool {
  return {
    id: 1,
    material: 'PLA',
    subtype: null,
    color_name: null,
    rgba: 'ffffff',
    extra_colors: null,
    effect_type: null,
    brand: 'Generic',
    label_weight: 1000,
    core_weight: 250,
    core_weight_catalog_id: null,
    weight_used: 0,
    slicer_filament: null,
    slicer_filament_name: null,
    nozzle_temp_min: null,
    nozzle_temp_max: null,
    note: null,
    added_full: true,
    last_used: null,
    encode_time: null,
    tag_uid: null,
    tray_uuid: null,
    data_origin: null,
    tag_type: null,
    archived_at: null,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    cost_per_kg: null,
    last_scale_weight: null,
    last_weighed_at: null,
    category: null,
    low_stock_threshold_pct: null,
    storage_location: null,
    ...overrides,
  } as InventorySpool;
}

function tray(overrides: Partial<AMSTray>): AMSTray {
  return {
    id: 0,
    tray_color: null,
    tray_type: null,
    tray_sub_brands: null,
    tray_id_name: null,
    tray_info_idx: null,
    remain: -1,
    k: null,
    cali_idx: null,
    tag_uid: null,
    tray_uuid: null,
    nozzle_temp_min: null,
    nozzle_temp_max: null,
    drying_temp: null,
    drying_time: null,
    state: null,
    ...overrides,
  };
}

function ams(overrides: Partial<AMSUnit>): AMSUnit {
  return {
    id: 0,
    name: null,
    humidity: null,
    temp: null,
    is_ams_ht: false,
    tray: [],
    serial_number: 'AMS123',
    sw_ver: '1.0.0',
    dry_time: 0,
    dry_status: 0,
    dry_sub_status: 0,
    dry_sf_reason: [],
    module_type: 'ams',
    ...overrides,
  };
}

function status(overrides: Partial<PrinterStatus>): PrinterStatus {
  return {
    id: 1,
    name: 'P1S',
    connected: true,
    state: 'RUNNING',
    current_print: 'test.3mf',
    subtask_name: null,
    current_archive_id: null,
    current_plate_id: null,
    gcode_file: null,
    progress: 12,
    remaining_time: 60,
    layer_num: null,
    total_layers: null,
    temperatures: null,
    cover_url: null,
    hms_errors: [],
    ams: [],
    ams_exists: false,
    vt_tray: [],
    store_to_sdcard: false,
    timelapse: false,
    ipcam: false,
    wifi_signal: null,
    wired_network: false,
    door_open: false,
    nozzles: [],
    nozzle_rack: [],
    print_options: null,
    stg_cur: -1,
    stg_cur_name: null,
    stg: [],
    airduct_mode: 0,
    speed_level: 2,
    chamber_light: false,
    active_extruder: 0,
    ams_mapping: [],
    ams_extruder_map: {},
    fila_switch: null,
    tray_now: 0,
    ams_status_main: 0,
    ams_status_sub: 0,
    mc_print_sub_stage: 0,
    last_ams_update: 0,
    printable_objects_count: 1,
    cooling_fan_speed: null,
    big_fan1_speed: null,
    big_fan2_speed: null,
    heatbreak_fan_speed: null,
    firmware_version: null,
    connection_details: null,
    developer_mode: null,
    awaiting_plate_clear: false,
    supports_drying: false,
    ...overrides,
  };
}

const printer = { id: 7, name: 'P1S', serial_number: 'P1S123' } as Printer;

describe('resolveLoadedFilamentInfo', () => {
  it('prefers the assigned Spoolman spool for the currently active AMS slot', () => {
    const sunluAbs = spool({ id: 42, brand: 'Sunlu', material: 'ABS', color_name: 'Black', rgba: '111111', label_weight: 1000, weight_used: 250 });
    const result = resolveLoadedFilamentInfo({
      printer,
      status: status({
        tray_now: 2,
        ams: [ams({ id: 0, tray: [
          tray({ id: 0, tray_type: 'PLA', tray_color: 'FFFFFFFF', remain: 90 }),
          tray({ id: 1, tray_type: 'PETG', tray_color: '00FF00FF', remain: 80 }),
          tray({ id: 2, tray_type: 'ABS', tray_color: '111111FF', remain: 75 }),
        ] })],
      }),
      localAssignments: [],
      spoolmanSpools: [sunluAbs],
      spoolmanSlotAssignments: [{ printer_id: 7, printer_name: 'P1S', ams_id: 0, tray_id: 2, spoolman_spool_id: 42, ams_label: 'AMS' }],
    });

    expect(result).toMatchObject({
      material: 'Sunlu ABS Black',
      detail: 'AMS 0 tray 2',
      color: '111111',
      remainingPct: 75,
      source: 'spoolman',
      amsId: 0,
      trayId: 2,
      globalTrayId: 2,
    });
  });

  it('resolves AMS-HT active tray assignments by the AMS-HT global tray id', () => {
    const htSpool = spool({ id: 77, brand: 'Bambu', material: 'ASA', color_name: 'Gray', rgba: '777777', label_weight: 1000, weight_used: 100 });
    const result = resolveLoadedFilamentInfo({
      printer,
      status: status({
        tray_now: 128,
        ams: [ams({ id: 128, is_ams_ht: true, module_type: 'n3f', tray: [tray({ id: 0, tray_type: 'ASA', tray_color: '777777FF', remain: 60 })] })],
      }),
      localAssignments: [],
      spoolmanSpools: [htSpool],
      spoolmanSlotAssignments: [{ printer_id: 7, printer_name: 'P1S', ams_id: 128, tray_id: 0, spoolman_spool_id: 77, ams_label: 'AMS-HT' }],
    });

    expect(result).toMatchObject({
      material: 'Bambu ASA Gray',
      detail: 'AMS-HT 128 tray 0',
      remainingPct: 90,
      source: 'spoolman',
      amsId: 128,
      trayId: 0,
      globalTrayId: 128,
    });
  });

  it('uses local inventory assignment for an active AMS slot when Spoolman is unavailable', () => {
    const localSpool = spool({ id: 88, brand: 'Devil Design', material: 'PETG', color_name: 'Red', rgba: 'ff0000', label_weight: 1000, weight_used: 500 });
    const assignment = { printer_id: 7, ams_id: 1, tray_id: 3, spool: localSpool } as SpoolAssignment;
    const result = resolveLoadedFilamentInfo({
      printer,
      status: status({
        tray_now: 7,
        ams: [ams({ id: 1, tray: [tray({ id: 3, tray_type: 'PETG', tray_color: 'FF0000FF', remain: 45 })] })],
      }),
      localAssignments: [assignment],
      spoolmanSpools: [],
      spoolmanSlotAssignments: [],
    });

    expect(result).toMatchObject({
      material: 'Devil Design PETG Red',
      detail: 'AMS 1 tray 3',
      remainingPct: 50,
      source: 'inventory',
      amsId: 1,
      trayId: 3,
      globalTrayId: 7,
    });
  });

  it('falls back to active printer telemetry when no assignment exists', () => {
    const result = resolveLoadedFilamentInfo({
      printer,
      status: status({
        tray_now: 1,
        ams: [ams({ id: 0, tray: [
          tray({ id: 0, tray_type: 'PLA', tray_color: 'FFFFFFFF', remain: 90 }),
          tray({ id: 1, tray_type: 'ABS', tray_sub_brands: 'ABS-GF', tray_color: '222222FF', remain: 55 }),
        ] })],
      }),
      localAssignments: [],
      spoolmanSpools: [],
      spoolmanSlotAssignments: [],
    });

    expect(result).toMatchObject({
      material: 'ABS ABS-GF',
      detail: 'AMS 0 tray 1',
      color: '222222FF',
      remainingPct: 55,
      source: 'telemetry',
      amsId: 0,
      trayId: 1,
      globalTrayId: 1,
    });
  });
});
