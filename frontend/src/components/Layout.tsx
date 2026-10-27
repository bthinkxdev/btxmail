import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useMe, useAuth } from "../auth";
import { ROLE_LABEL } from "../format";
import { useInstall } from "../pwa";
import { pushSupported, syncPushSubscription, usePush } from "../push";
import { useToast } from "./ui";

export function Logo({ size = 26 }: { size?: number }) {
  return <img src="/logo-mark.png" width={size} height={size} alt="" className="logo-mark" />;
}

export default function Layout() {
  const me = useMe();
  const { logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const install = useInstall();
  const push = usePush();
  const [dismissed, setDismissed] = useState(() => {
    try {
      return localStorage.getItem("btx-push-dismissed") === "1";
    } catch {
      return false;
    }
  });
  useEffect(() => {
    void syncPushSubscription();
  }, []);
  const offerPush = pushSupported() && !push.subscribed && push.permission === "default" && !dismissed;
  const toast = useToast();
  const installApp = () => {
    if (install.kind === "prompt") install.install();
    else if (install.kind === "ios") toast.ok("Tap the Share button, then “Add to Home Screen”.");
    else toast.ok("Open your browser menu and choose “Install app” or “Add to Home screen”.");
  };
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
        <span className="topbar-actions">
          {install.kind !== "installed" && (
            <button type="button" onClick={installApp}>
              Install
            </button>
          )}
          <button onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-controls="sidebar">
            Menu
          </button>
        </span>
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
          {install.kind !== "installed" && (
            <button type="button" className="nav-install" onClick={installApp}>
              <span aria-hidden="true">⤓</span> Install app
            </button>
          )}
        </nav>
        <div className="sidebar-foot">
          <span className="who">{me.full_name || me.email}</span>
          <span>{me.business_name ?? ROLE_LABEL[me.role]}</span>
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
        {offerPush && (
          <div className="notice info push-offer" role="region" aria-label="Notifications">
            <span>Get a notification when new mail arrives or something needs your attention.</span>
            <span className="actions">
              <button
                type="button"
                className="btn primary small"
                disabled={push.busy}
                onClick={() => void push.enable().catch((e: unknown) => toast.error(e instanceof Error ? e.message : e))}
              >
                Turn on
              </button>
              <button
                type="button"
                className="btn small"
                onClick={() => {
                  setDismissed(true);
                  try {
                    localStorage.setItem("btx-push-dismissed", "1");
                  } catch {
                    /* storage unavailable */
                  }
                }}
              >
                Not now
              </button>
            </span>
          </div>
        )}
        <Outlet />
      </main>
    </div>
  );
}
