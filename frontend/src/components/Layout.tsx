import { useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useMe, useAuth } from "../auth";
import { ROLE_LABEL } from "../format";
import { useInstall } from "../pwa";

export function Logo({ size = 26 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <circle cx="16" cy="16" r="14" fill="none" stroke="#7d95ff" strokeWidth="2.5" />
      <path d="M8 12h16v10H8z M8 12l8 6 8-6" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinejoin="round" />
    </svg>
  );
}

export default function Layout() {
  const me = useMe();
  const { logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const install = useInstall();
  const [open, setOpen] = useState(false);
  const [lastPath, setLastPath] = useState(location.pathname);
  if (lastPath !== location.pathname) {
    setLastPath(location.pathname);
    setOpen(false);
  }

  const staff = me.is_platform_staff;
  return (
    <div className="shell">
      <div className="topbar-mobile">
        <span className="brand" style={{ padding: 0 }}>
          <Logo size={22} /> BThinkX Mail
        </span>
        <button onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-controls="sidebar">
          Menu
        </button>
      </div>
      {open && <div className="scrim" onClick={() => setOpen(false)} aria-hidden="true" />}
      <aside id="sidebar" className={`sidebar${open ? " open" : ""}`}>
        <div className="brand">
          <Logo /> BThinkX Mail
        </div>
        <nav className="nav" aria-label="Main">
          <NavLink to="/" end>
            Overview
          </NavLink>
          {staff && <NavLink to="/businesses">Businesses</NavLink>}
          <NavLink to="/domains">Domains</NavLink>
          <NavLink to="/mailboxes">Mailboxes</NavLink>
          <NavLink to="/aliases">Forwarding</NavLink>
          <div className="nav-group">Safety</div>
          <NavLink to="/security">Security events</NavLink>
          <NavLink to="/audit">Activity log</NavLink>
          <div className="nav-group">Administration</div>
          <NavLink to="/users">Portal users</NavLink>
          {staff && <NavLink to="/plans">Plans</NavLink>}
          {staff && <NavLink to="/system">Mail server health</NavLink>}
          <NavLink to="/account">My account</NavLink>
        </nav>
        <div className="sidebar-foot">
          <span className="who">{me.full_name || me.email}</span>
          <span>{me.business_name ?? ROLE_LABEL[me.role]}</span>
          {install.kind === "prompt" && (
            <button type="button" onClick={install.install}>
              Install app
            </button>
          )}
          {install.kind === "ios" && <span>To install: tap Share, then “Add to Home Screen”.</span>}
          <button
            onClick={async () => {
              await logout();
              navigate("/login", { replace: true });
            }}
          >
            Sign out
          </button>
        </div>
      </aside>
      <main className="main" id="content">
        <Outlet />
      </main>
    </div>
  );
}
