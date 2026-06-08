# Printbuddy provider roadmap

## Goal

Support Bambu Lab, Klipper, and Mainsail/Moonraker printers behind one provider-aware app model.

## Providers

- `bambu`: existing Bambu Lab MQTT/FTP implementation from the original foundation.
- `klipper`: Moonraker API/WebSocket implementation for Klipper printers.
- `mainsail`: UI label for printers managed through Mainsail; technically uses Moonraker like Klipper.

## Architecture rules

1. Keep Bambu behavior backwards-compatible.
2. Add provider metadata to the `Printer` model instead of overloading Bambu fields.
3. Route provider-specific clients through `backend.app.services.printer_providers.factory`.
4. Gate Bambu-only features such as AMS, FTP file browser, calibration, and drying commands until a capability model exists.
5. Build Moonraker support incrementally: connection test, status, temperatures, file list, print start/stop, then advanced controls.

## First scaffold

The initial `dev` branch setup includes:

- provider fields on printers: `provider`, `api_url`, `auth_token`, `provider_options`
- DB migration entries for those fields
- provider factory with `bambu`, `klipper`, and `mainsail`
- minimal Moonraker client scaffold
- Printbuddy branding and dev-branch CI

## Next implementation step

Wire the add/edit printer UI to select provider and conditionally show:

- Bambu Lab: serial number + access code + IP
- Klipper/Mainsail: Moonraker URL + optional token

Then update API create/test routes to validate each provider through its own connection probe.
