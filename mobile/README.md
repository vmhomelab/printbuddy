# Printbuddy Mobile

Native companion app for a self-hosted Printbuddy server (iOS and Android), built with Expo / React Native and Expo Router.

## Features (v0.1)

- Connect to any Printbuddy server by address (LAN, reverse proxy, VPN or Tailscale)
- Sign in with username and password (including 2FA via TOTP, email or backup code) or with an API key
- Credentials are stored in the iOS Keychain / Android Keystore (`expo-secure-store`)
- Printer list with live status over the `/api/v1/ws` WebSocket: state, progress, remaining time, temperatures, alerts
- Printer detail: camera snapshot (refreshed every 3 s), job progress, ETA, layers, temperatures
- Pause, resume and stop (stop asks for confirmation first)
- German and English, following the device language. Light and dark mode.

## Development

```bash
cd mobile
npm install
npx expo start
```

Then scan the QR code with **Expo Go** on your phone. The phone needs to be able to reach both the dev machine and the Printbuddy server.

The quickest way to sign in is with an API key: in Printbuddy go to Settings → API keys and enable "Control printer" if you want to pause or stop prints from the app.

### Checks

```bash
npm run typecheck   # app + tests
npm test            # unit tests (node:test, no extra dependencies)
```

`src/lib/` holds the logic (API client, URL handling, formatting, WebSocket reducer) with no React Native imports, so it can be tested directly with Node.

## Builds

Native builds go through EAS (no Xcode or Android Studio needed):

```bash
npx eas-cli@latest build --profile preview --platform android
npx eas-cli@latest build --profile preview --platform ios
```

iOS needs an Apple Developer account. Store releases also need a Google Play Console account.

## Notes

- Plain `http://` servers are allowed (`NSAllowsArbitraryLoads` on iOS, `usesCleartextTraffic` on Android), because many home setups run without TLS. For access from outside your home network, use HTTPS or a VPN.
- The backend sends no CORS headers. That does not matter for the native app; the web build (`npx expo start --web`) only works when it is served from the same origin as the server.
- The camera uses snapshots, not the MJPEG stream, so it works the same with every provider.

## Planned

- Push notifications (print finished / failed / HMS errors) via APNs and FCM
- iOS Live Activity and home screen widget
- Print queue and archive
- Setting the server up by QR code from the web interface
