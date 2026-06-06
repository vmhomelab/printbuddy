# Security Policy

The Printbuddy maintainers take security seriously. We appreciate responsible disclosure and will handle security reports with care.

## Reporting a Vulnerability

Please report security vulnerabilities privately through GitHub Security Advisories:

1. Go to the [Security tab](https://github.com/vmhomelab/Printbuddy/security)
2. Click **Report a vulnerability**
3. Include as much detail as possible

Please do **not** open public issues for vulnerabilities.

## What to Include

- Affected Printbuddy version or commit
- Installation method: Docker, native install, Home Assistant add-on, or source checkout
- A clear description of the vulnerability and impact
- Reproduction steps or proof of concept, if safe to share
- Relevant logs, screenshots, or configuration snippets with secrets removed

## Supported Versions

Security fixes are applied to the active `main` release line. Development fixes land on `dev` first when testing is required, then are merged to `main` before release.

## Network and Credential Notes

Printbuddy communicates with printers and integrations over your local network. Treat the instance like any other self-hosted service that can reach trusted LAN devices:

- Run it only on a trusted network or behind your own access controls.
- Use authentication for shared or exposed instances.
- Keep API keys, printer access codes, MQTT credentials, SMTP credentials, and cloud tokens private.
- Do not publish support bundles without reviewing them for environment-specific details.

Thank you for helping keep Printbuddy and its users safe.
