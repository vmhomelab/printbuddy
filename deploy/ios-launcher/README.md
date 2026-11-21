# Printbuddy iPhone launcher

A home-screen web app for iPhone that opens Printbuddy full screen (no Safari bar),
using the local address on home Wi-Fi and a Tailscale address everywhere else.

## Files
- `launcher.html` - checks the local address for 1.5 s, else opens the Tailscale one in a full-screen frame
- `launcher.conf` - nginx proxy: serves the launcher and pins the app layout so only the page content scrolls
- `icon-180.png`, `icon-512.png` - app icons (180 = iOS apple-touch-icon)

## Setup (Docker host running Printbuddy on port 8000)
1. Allow the launcher to frame Printbuddy. Add both launcher origins to the app's
   environment (e.g. in `.env` or `docker-compose.yml`) and restart Printbuddy:
   ```
   TRUSTED_FRAME_ORIGINS=http://YOUR_LOCAL_IP:8080,http://YOUR_TAILSCALE_IP:8080
   ```
2. Edit `launcher.html`: set `YOUR_LOCAL_IP` and `YOUR_TAILSCALE_IP`.
3. Copy this folder to the host, e.g. `~/ios-launcher`.
4. Run:
   ```
   docker run -d --name printbuddy-launcher --restart unless-stopped --network host \
     -v ~/ios-launcher:/usr/share/nginx/html:ro \
     -v ~/ios-launcher/launcher.conf:/etc/nginx/conf.d/default.conf:ro nginx:alpine
   ```
5. On the iPhone, open `http://YOUR_TAILSCALE_IP:8080/launcher.html` in Safari, then Share > Add to Home Screen.
6. Allow Local Network access when iOS asks.

## Why the proxy
Printbuddy already ships a PWA manifest, so "Add to Home Screen" works without this launcher.
The launcher adds automatic switching between the home Wi-Fi address and the Tailscale address,
which a single installed PWA cannot do because it is bound to one origin.

The launcher frames the app, and the proxy injects a small style so the framed app does not
scroll as a whole. Framing itself is controlled by Printbuddy via `TRUSTED_FRAME_ORIGINS`;
without it the app sends `X-Frame-Options: SAMEORIGIN` and `frame-ancestors 'none'` and the
frame stays blank.
