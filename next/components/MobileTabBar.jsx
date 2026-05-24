import React, { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Home, Search, LayoutGrid, MapPin, Menu, Info, Phone, Building2, ShieldCheck, FileText } from 'lucide-react';
import { useCity } from '../context/CityContext';
import {
  Drawer, DrawerContent, DrawerHeader, DrawerTitle, DrawerDescription, DrawerClose,
} from './ui/drawer';
import { openSearchOverlay } from '../lib/searchOverlay';

// We keep tabbar links on city.id (msk/spb) so they match the sitemap and the
// SSR-rendered canonical URLs.  Home.jsx accepts both `/msk` and `/moskva` as
// safe aliases, but the canonical form for crawlers stays `/msk`.

// Returns true when the given href best matches current location.
function isActive(pathname, target) {
  if (target === 'home') return pathname === '/' || /^\/[a-z-]+\/?$/.test(pathname);
  if (target === 'search') return /\/poisk(\b|$)/.test(pathname);
  if (target === 'catalog') return /\/kategorii(\b|$)/.test(pathname) || /\/preparaty(\b|$)/.test(pathname);
  if (target === 'pharmacies') return /\/apteki(\b|$)/.test(pathname);
  return false;
}

/**
 * Tracks the offset between layout-viewport bottom and visual-viewport bottom
 * (i.e. how much space iOS Safari/Chrome bottom UI currently occupies).
 *
 * The tabbar uses this so it floats just above the collapsing Chrome address
 * bar rather than leaving a transparent gap, and so it does not over-reserve
 * space when iOS Safari's chrome is at full height.
 */
function useVisualViewportBottom() {
  const [offset, setOffset] = useState(0);
  useEffect(() => {
    const vv = typeof window !== 'undefined' ? window.visualViewport : null;
    if (!vv) return;
    const update = () => {
      const bottomOffset = window.innerHeight - vv.height - vv.offsetTop;
      const clamped = Math.max(0, Math.min(160, bottomOffset));
      setOffset(clamped);
    };
    update();
    vv.addEventListener('resize', update);
    vv.addEventListener('scroll', update);
    return () => {
      vv.removeEventListener('resize', update);
      vv.removeEventListener('scroll', update);
    };
  }, []);
  return offset;
}

// Expose vvBottom + tabbar offset as CSS variables for other components
// (Footer, content padding) to use. On desktop (md+) we set the offset to 0
// so the footer / page chrome doesn't reserve unused space.
function useVvBottomCssVar(vvBottom) {
  useEffect(() => {
    const apply = () => {
      const mql = window.matchMedia && window.matchMedia('(min-width: 768px)');
      const isDesktop = mql ? mql.matches : false;
      const tabbarOffset = isDesktop
        ? '0px'
        : `calc(64px + max(${vvBottom}px, env(safe-area-inset-bottom)))`;
      document.documentElement.style.setProperty('--vv-bottom', `${vvBottom}px`);
      document.documentElement.style.setProperty('--tabbar-offset', tabbarOffset);
    };
    apply();
    const mql = window.matchMedia && window.matchMedia('(min-width: 768px)');
    if (mql && mql.addEventListener) mql.addEventListener('change', apply);
    return () => {
      if (mql && mql.removeEventListener) mql.removeEventListener('change', apply);
    };
  }, [vvBottom]);
}

export default function MobileTabBar() {
  const location = useLocation();
  const navigate = useNavigate();
  const { city } = useCity();
  const [moreOpen, setMoreOpen] = useState(false);
  const vvBottom = useVisualViewportBottom();
  useVvBottomCssVar(vvBottom);

  // Show a 1-time ping animation on the Search tab for first-time visitors so
  // they discover it as the primary action. Runs ~3.6s, then the flag is set
  // in localStorage and the animation never plays again on this device.
  const [showSearchHint, setShowSearchHint] = useState(false);
  useEffect(() => {
    try {
      if (typeof window === 'undefined') return;
      const KEY = 'aptekaa.tabbarSearchHintShown';
      if (window.localStorage.getItem(KEY)) return;
      // Delay slightly so the tabbar is mounted and visible.
      const t1 = setTimeout(() => setShowSearchHint(true), 700);
      const t2 = setTimeout(() => {
        setShowSearchHint(false);
        try { window.localStorage.setItem(KEY, '1'); } catch {}
      }, 700 + 3700);
      return () => { clearTimeout(t1); clearTimeout(t2); };
    } catch { /* localStorage blocked — skip the hint */ }
  }, []);

  const cityPrefix = city?.id ? `/${city.id}` : '';

  // Order requested by product: Home, Catalog, Search (center), Pharmacies, More.
  const items = [
    { key: 'home', label: 'Главная', icon: Home, to: `${cityPrefix}` || '/' },
    { key: 'catalog', label: 'Каталог', icon: LayoutGrid, to: `${cityPrefix}/kategorii` },
    { key: 'search', label: 'Поиск', icon: Search, action: openSearchOverlay },
    { key: 'pharmacies', label: 'Аптеки', icon: MapPin, to: `${cityPrefix}/apteki` },
    { key: 'more', label: 'Ещё', icon: Menu, action: () => setMoreOpen(true) },
  ];

  // Tabbar floats at `max(visualViewportBottom, safe-area-inset-bottom)` and
  // has a constant 64px intrinsic height (no internal safe-area padding).
  const tabbarStyle = {
    bottom: `max(${vvBottom}px, env(safe-area-inset-bottom))`,
    height: '64px',
  };
  const shieldStyle = {
    bottom: 0,
    height: `max(${vvBottom}px, env(safe-area-inset-bottom))`,
  };

  return (
    <>
      <nav
        className="md:hidden fixed left-0 right-0 z-50 bg-white/95 backdrop-blur-lg border-t border-slate-200 flex items-stretch justify-around px-1"
        style={tabbarStyle}
        data-testid="mobile-tabbar"
        role="navigation"
        aria-label="Основная навигация"
      >
        {items.map(({ key, label, icon: Icon, to, action }) => {
          const active = isActive(location.pathname, key);
          // The Search tab is always rose-red — both as a visual anchor
          // (mirrors the rose magnifier inside the Header search box) and to
          // draw attention to the primary action on the bar.
          const isSearchTab = key === 'search';
          const iconCls = isSearchTab
            ? 'text-rose-500'
            : (active ? 'text-emerald-600' : 'text-slate-500');
          const labelCls = isSearchTab
            ? 'text-rose-500'
            : (active ? 'text-emerald-600' : 'text-slate-500');
          const pulseCls = isSearchTab && showSearchHint ? ' tabbar-pulse' : '';
          const baseCls =
            'flex flex-col items-center justify-center gap-0.5 min-w-[56px] flex-1 max-w-[80px] h-full transition-colors' + pulseCls;
          const content = (
            <>
              <Icon className={`w-5 h-5 ${iconCls}`} strokeWidth={active ? 2.4 : 1.8} />
              <span className={`text-[11px] font-medium tracking-tight ${labelCls}`}>{label}</span>
            </>
          );
          if (action) {
            return (
              <button
                key={key}
                type="button"
                onClick={action}
                className={baseCls}
                data-testid={`tabbar-${key}`}
                aria-label={label}
              >
                {content}
              </button>
            );
          }
          return (
            <Link
              key={key}
              to={to}
              className={baseCls}
              data-testid={`tabbar-${key}`}
              aria-label={label}
            >
              {content}
            </Link>
          );
        })}
      </nav>

      {/* Background shield below the tabbar — fills the gap between tabbar and
          the live system UI so the user never sees the page showing through. */}
      <div
        aria-hidden="true"
        className="md:hidden fixed left-0 right-0 z-40 bg-white pointer-events-none"
        style={shieldStyle}
        data-testid="mobile-tabbar-shield"
      />

      <Drawer open={moreOpen} onOpenChange={setMoreOpen}>
        <DrawerContent className="md:hidden" data-testid="more-drawer">
          <DrawerHeader className="text-left">
            <DrawerTitle>Ещё</DrawerTitle>
            <DrawerDescription className="sr-only">Дополнительные разделы сайта</DrawerDescription>
          </DrawerHeader>
          <div className="px-4 pb-6 grid grid-cols-1 gap-1">
            {[
              { to: '/dlya-aptek', label: 'Для аптек', icon: Building2 },
              { to: '/o-servise', label: 'О сервисе', icon: Info },
              { to: '/kontakty', label: 'Контакты', icon: Phone },
              { to: '/politika-konfidencialnosti', label: 'Конфиденциальность', icon: ShieldCheck },
              { to: '/soglasie-na-obrabotku-pd', label: 'Согласие на ОПД', icon: FileText },
            ].map(({ to, label, icon: Icon }) => (
              <button
                key={to}
                type="button"
                onClick={() => { setMoreOpen(false); navigate(to); }}
                className="flex items-center gap-3 px-3 py-3.5 rounded-xl text-slate-800 hover:bg-slate-50 active:bg-slate-100 text-left transition"
                data-testid={`more-${to.replace(/[^a-z]/g, '')}`}
              >
                <Icon className="w-5 h-5 text-emerald-600 shrink-0" />
                <span className="text-base font-medium">{label}</span>
              </button>
            ))}
            <DrawerClose asChild>
              <button
                type="button"
                className="mt-3 mx-1 h-12 rounded-xl border border-slate-200 text-slate-700 font-medium active:bg-slate-50"
                data-testid="more-close"
              >
                Закрыть
              </button>
            </DrawerClose>
          </div>
        </DrawerContent>
      </Drawer>
    </>
  );
}
