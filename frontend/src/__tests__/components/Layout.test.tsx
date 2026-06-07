/**
 * Tests for the Layout component.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { render } from '../utils';
import { Layout } from '../../components/Layout';
import { http, HttpResponse } from 'msw';
import { server } from '../mocks/server';

describe('Layout', () => {
  beforeEach(() => {
    localStorage.clear();
    window.history.replaceState({}, '', '/');
    vi.mocked(localStorage.getItem).mockReset();
    vi.mocked(localStorage.setItem).mockReset();
    vi.mocked(localStorage.removeItem).mockReset();
    vi.mocked(localStorage.clear).mockReset();

    server.use(
      http.get('/api/v1/printers/', () => {
        return HttpResponse.json([
          { id: 1, name: 'X1 Carbon', model: 'X1C', enabled: true },
        ]);
      }),
      http.get('/api/v1/printers/:id/status', () => {
        return HttpResponse.json({
          connected: true,
          state: 'IDLE',
        });
      }),
      http.get('/api/v1/updates/version', () => {
        return HttpResponse.json({
          version: '0.1.6',
          display_version: '0.1.6 (abc1234)',
          source_ref: 'abc1234567890abc1234567890abc1234567890ab',
          source_ref_short: 'abc1234',
          repo: 'vmhomelab/Printbuddy',
        });
      }),
      http.get('/api/v1/settings/', () => {
        return HttpResponse.json({
          check_updates: false,
          check_printer_firmware: false,
          auto_archive: true,
        });
      }),
      http.get('/api/v1/external-links/', () => {
        return HttpResponse.json([]);
      }),
      http.get('/api/v1/smart-plugs/', () => {
        return HttpResponse.json([]);
      }),
      http.get('/api/v1/support/debug-logging', () => {
        return HttpResponse.json({ enabled: false });
      }),
      http.get('/api/v1/queue/', () => {
        return HttpResponse.json([]);
      }),
      http.get('/api/v1/pending-uploads/count', () => {
        return HttpResponse.json({ count: 0 });
      }),
      http.get('/api/v1/updates/check', () => {
        return HttpResponse.json({ update_available: false });
      }),
      http.get('/api/v1/auth/status', () => {
        return HttpResponse.json({ auth_enabled: false, requires_setup: false });
      }),
      http.get('/api/v1/printers/developer-mode-warnings', () => {
        return HttpResponse.json([]);
      })
    );
  });

  describe('rendering', () => {
    it('renders the sidebar', async () => {
      render(<Layout />);

      // Layout renders as a flex container with sidebar
      await waitFor(() => {
        const sidebar = document.querySelector('aside');
        expect(sidebar).toBeInTheDocument();
      });
    });

    it('renders navigation links', async () => {
      render(<Layout />);

      await waitFor(() => {
        // Navigation links should be present
        const links = document.querySelectorAll('a');
        expect(links.length).toBeGreaterThan(0);
      });
    });
  });

  describe('navigation', () => {
    it('has navigation items', async () => {
      render(<Layout />);

      await waitFor(() => {
        // Should have multiple navigation links
        const navLinks = document.querySelectorAll('a[href]');
        expect(navLinks.length).toBeGreaterThan(0);
      });
    });

    it('includes settings link', async () => {
      render(<Layout />);

      await waitFor(() => {
        // Settings link should exist (route /settings)
        const settingsLink = document.querySelector('a[href="/settings"]');
        expect(settingsLink).toBeInTheDocument();
      });
    });
  });

  describe('version display', () => {
    it('shows the backend version and running repository revision in the sidebar footer', async () => {
      render(<Layout />);

      await waitFor(() => {
        expect(document.body.textContent).toContain('v0.1.6 (abc1234)');
      });
      expect(document.body.textContent).not.toContain('printbuddy.');
    });
  });

  describe('AGPL source access', () => {
    it('shows a prominent source-code link in the sidebar footer', async () => {
      render(<Layout />);

      const sourceLink = await screen.findByRole('link', { name: /source code/i });
      expect(sourceLink).toHaveAttribute('href', 'https://github.com/vmhomelab/Printbuddy');
    });
  });

  describe('theme-aware branding', () => {
    it('uses the dark-mode Printbuddy logo when the app theme is dark', async () => {
      vi.mocked(localStorage.getItem).mockImplementation((key: string) => (
        key === 'theme-mode' ? 'dark' : null
      ));

      render(<Layout />);

      const logo = await waitFor(() => document.querySelector('img[alt="Printbuddy"]')) as HTMLImageElement;
      expect(logo).toBeInTheDocument();
      expect(logo.getAttribute('src')).toBe('/img/printbuddy_logo_dark.png');
      await waitFor(() => {
        expect(document.head.querySelector('link[rel="icon"][sizes="32x32"]')).toHaveAttribute('href', '/img/favicon-32x32-dark.png');
      });
    });

    it('uses the light-mode Printbuddy logo when the app theme is light', async () => {
      vi.mocked(localStorage.getItem).mockImplementation((key: string) => (
        key === 'theme-mode' ? 'light' : null
      ));

      render(<Layout />);

      const logo = await waitFor(() => document.querySelector('img[alt="Printbuddy"]')) as HTMLImageElement;
      expect(logo).toBeInTheDocument();
      expect(logo.getAttribute('src')).toBe('/img/printbuddy_logo_light.png');
      await waitFor(() => {
        expect(document.head.querySelector('link[rel="icon"][sizes="32x32"]')).toHaveAttribute('href', '/img/favicon-32x32.png');
      });
    });

    it('uses only the Printbuddy icon when the desktop sidebar is collapsed', async () => {
      vi.mocked(localStorage.getItem).mockImplementation((key: string) => {
        if (key === 'theme-mode') return 'dark';
        if (key === 'sidebarExpanded') return 'false';
        return null;
      });

      render(<Layout />);

      const logo = await waitFor(() => document.querySelector('aside img[alt="Printbuddy"]')) as HTMLImageElement;
      expect(logo).toBeInTheDocument();
      expect(logo.getAttribute('src')).toBe('/img/printbuddy_icon_dark.png');
      expect(logo).toHaveClass('h-8', 'w-8');
    });

    it('prefixes the sidebar logo and favicon when running under Home Assistant ingress', async () => {
      window.history.replaceState({}, '', '/api/hassio_ingress/test-token/');
      vi.mocked(localStorage.getItem).mockImplementation((key: string) => (
        key === 'theme-mode' ? 'dark' : null
      ));

      render(<Layout />);

      const logo = await waitFor(() => document.querySelector('img[alt="Printbuddy"]')) as HTMLImageElement;
      expect(logo).toBeInTheDocument();
      expect(logo.getAttribute('src')).toBe('/api/hassio_ingress/test-token/img/printbuddy_logo_dark.png');
      await waitFor(() => {
        expect(document.head.querySelector('link[rel="icon"][sizes="32x32"]')).toHaveAttribute(
          'href',
          '/api/hassio_ingress/test-token/img/favicon-32x32-dark.png'
        );
      });
    });
  });

  describe('theme toggle', () => {
    it('has theme toggle button', async () => {
      render(<Layout />);

      await waitFor(() => {
        // Theme toggle should be present
        const buttons = document.querySelectorAll('button');
        expect(buttons.length).toBeGreaterThan(0);
      });
    });
  });

  describe('plate detection alert modal', () => {
    it('shows modal when plate-not-empty event is dispatched', async () => {
      render(<Layout />);

      // Dispatch the plate-not-empty event
      window.dispatchEvent(
        new CustomEvent('plate-not-empty', {
          detail: {
            printer_id: 1,
            printer_name: 'Test Printer',
            message: 'Objects detected on build plate',
          },
        })
      );

      await waitFor(() => {
        // Modal should appear with "Print Paused!" text
        expect(document.body.textContent).toContain('Print Paused!');
        expect(document.body.textContent).toContain('Test Printer');
      });
    });

    it('closes modal when I Understand button is clicked', async () => {
      render(<Layout />);

      // Dispatch the plate-not-empty event
      window.dispatchEvent(
        new CustomEvent('plate-not-empty', {
          detail: {
            printer_id: 1,
            printer_name: 'Test Printer',
            message: 'Objects detected on build plate',
          },
        })
      );

      await waitFor(() => {
        expect(document.body.textContent).toContain('Print Paused!');
      });

      // Click the "I Understand" button
      const button = document.querySelector('button');
      if (button && button.textContent?.includes('I Understand')) {
        button.click();
      }

      // Find and click the "I Understand" button by searching all buttons
      const buttons = document.querySelectorAll('button');
      buttons.forEach((btn) => {
        if (btn.textContent?.includes('I Understand')) {
          btn.click();
        }
      });

      await waitFor(() => {
        // Modal should be closed
        expect(document.body.textContent).not.toContain('Print Paused!');
      });
    });
  });

  describe('developer mode warning banner', () => {
    it('shows warning banner when printers lack developer mode', async () => {
      server.use(
        http.get('/api/v1/printers/developer-mode-warnings', () => {
          return HttpResponse.json([
            { printer_id: 1, name: 'X1 Carbon' },
          ]);
        })
      );

      render(<Layout />);

      await waitFor(() => {
        expect(document.body.textContent).toContain('Developer LAN mode is not enabled on');
        expect(document.body.textContent).toContain('X1 Carbon');
      });
    });

    it('shows multiple printer names in warning banner', async () => {
      server.use(
        http.get('/api/v1/printers/developer-mode-warnings', () => {
          return HttpResponse.json([
            { printer_id: 1, name: 'X1 Carbon' },
            { printer_id: 2, name: 'P1S' },
          ]);
        })
      );

      render(<Layout />);

      await waitFor(() => {
        expect(document.body.textContent).toContain('X1 Carbon');
        expect(document.body.textContent).toContain('P1S');
      });
    });

    it('hides warning banner when no printers lack developer mode', async () => {
      // Default handler returns empty array
      render(<Layout />);

      await waitFor(() => {
        const sidebar = document.querySelector('aside');
        expect(sidebar).toBeInTheDocument();
      });

      // Banner should not be present
      expect(document.body.textContent).not.toContain('Developer LAN mode is not enabled on');
    });

    it('shows how to enable link in warning banner', async () => {
      server.use(
        http.get('/api/v1/printers/developer-mode-warnings', () => {
          return HttpResponse.json([
            { printer_id: 1, name: 'X1 Carbon' },
          ]);
        })
      );

      render(<Layout />);

      await waitFor(() => {
        expect(document.body.textContent).toContain('How to enable');
        const link = document.querySelector('a[href*="enable-developer-mode"]');
        expect(link).toBeInTheDocument();
      });
    });
  });

  describe('update banner suppression for HA addon', () => {
    // HA Supervisor surfaces its own update notification natively in the HA
    // UI, so the in-app banner would be duplicate noise that links to a page
    // that just says "update via HA". Suppress it for HA addon deployments.
    it('hides the update-available banner when running as an HA addon', async () => {
      server.use(
        http.get('/api/v1/updates/check', () => {
          return HttpResponse.json({
            update_available: true,
            current_version: '0.2.4',
            latest_version: '0.2.5',
            is_docker: true,
            is_ha_addon: true,
            update_method: 'ha_addon',
          });
        }),
      );

      render(<Layout />);

      await waitFor(() => {
        const sidebar = document.querySelector('aside');
        expect(sidebar).toBeInTheDocument();
      });

      expect(document.body.textContent).not.toContain('Update available');
    });

    it('still shows the update-available banner for plain Docker deployments', async () => {
      server.use(
        http.get('/api/v1/updates/check', () => {
          return HttpResponse.json({
            update_available: true,
            current_version: '0.2.4',
            latest_version: '0.2.5',
            is_docker: true,
            is_ha_addon: false,
            update_method: 'docker',
          });
        }),
      );

      render(<Layout />);

      await waitFor(() => {
        expect(document.body.textContent).toContain('0.2.5');
      });
    });
  });

  describe('MakerWorld sidebar permission gate (#1175)', () => {
    // The MakerWorld sidebar entry was visible to every authenticated user
    // regardless of group permissions because Layout's `navPermissions` map
    // had no entry for `makerworld`. Backend routes already gated on
    // `makerworld:view`, so users without the permission saw the entry,
    // clicked, and got 403'd by every API call inside the page. The fix
    // adds `makerworld: 'makerworld:view'` to the map so the entry is
    // hidden when the permission is absent — same shape as every other
    // sidebar entry.
    const enableAuthWithUser = (permissions: string[]) => {
      server.use(
        http.get('/api/v1/auth/status', () =>
          HttpResponse.json({ auth_enabled: true, requires_setup: false }),
        ),
        http.get('/api/v1/auth/me', () =>
          HttpResponse.json({
            id: 1,
            username: 'tester',
            role: 'user',
            is_active: true,
            is_admin: false,
            groups: [{ id: 2, name: 'Standard Users' }],
            permissions,
            created_at: '2026-01-01T00:00:00Z',
          }),
        ),
      );
      // AuthProvider needs a token in localStorage to fetch /auth/me; the
      // value isn't validated by the mocked server.
      window.localStorage.setItem('auth_token', 'test-token');
    };

    const findMakerWorldNavLink = () => {
      // Sidebar nav links use react-router's `to` prop, which renders as a
      // plain `<a href="/makerworld">`. Match on the href so the test isn't
      // coupled to whatever locale string is rendered.
      return document.querySelector('aside a[href="/makerworld"]');
    };

    it('hides the MakerWorld nav entry when the user lacks makerworld:view', async () => {
      // Standard user without the MakerWorld permission. Every other
      // permission they hold (library:read, etc.) is irrelevant here — the
      // gate is per-entry and the MakerWorld entry must not render.
      enableAuthWithUser(['library:read', 'archives:read', 'queue:read']);

      render(<Layout />);

      await waitFor(() => {
        // Wait for the auth resolution + sidebar render. Some other nav
        // entry (Files / Archives) confirms the sidebar finished mounting.
        const sidebar = document.querySelector('aside');
        expect(sidebar).toBeInTheDocument();
        expect(sidebar?.querySelector('a[href="/files"]')).toBeInTheDocument();
      });

      expect(findMakerWorldNavLink()).toBeNull();
    });

    it('shows the MakerWorld nav entry when the user has makerworld:view', async () => {
      enableAuthWithUser([
        'library:read',
        'archives:read',
        'queue:read',
        'makerworld:view',
      ]);

      render(<Layout />);

      await waitFor(() => {
        expect(findMakerWorldNavLink()).toBeInTheDocument();
      });
    });
  });
});
