import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { useTheme } from "../lib/theme";
import { cx } from "./ui";

const NAV: { to: string; label: string; icon: string; admin?: boolean }[] = [
  { to: "/", label: "Fleet overview", icon: "M3 13h8V3H3zm10 8h8V11h-8zM3 21h8v-6H3zm10-18v6h8V3z" },
  { to: "/equipment", label: "Equipment", icon: "M4 6h16M4 12h16M4 18h10" },
  { to: "/sensors", label: "Sensor monitoring", icon: "M3 12h4l3-8 4 16 3-8h4" },
  { to: "/predictions", label: "Failure prediction", icon: "M12 3v18M5 10l7-7 7 7" },
  { to: "/anomalies", label: "Anomaly detection", icon: "M12 9v4m0 4h.01M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z" },
  { to: "/work-orders", label: "Work orders", icon: "M9 5h10M9 12h10M9 19h10M4 5h.01M4 12h.01M4 19h.01" },
  { to: "/models", label: "Model performance", icon: "M4 19V9m6 10V5m6 14v-7m4 7H2" },
  { to: "/reports", label: "Reports", icon: "M7 3h7l5 5v13H7zM14 3v5h5" },
  { to: "/admin", label: "Administration", icon: "M12 15a3 3 0 100-6 3 3 0 000 6zm7.4-3a7.4 7.4 0 00-.1-1.2l2-1.6-2-3.4-2.4 1a7.6 7.6 0 00-2-1.2L14.5 3h-4l-.4 2.6a7.6 7.6 0 00-2 1.2l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 000 2.4l-2 1.6 2 3.4 2.4-1a7.6 7.6 0 002 1.2l.4 2.6h4l.4-2.6a7.6 7.6 0 002-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2z", admin: true },
];

function Icon({ d }: { d: string }) {
  return <svg aria-hidden viewBox="0 0 24 24" className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round"><path d={d} /></svg>;
}

export default function Layout() {
  const { user, logout, can } = useAuth();
  const { theme, toggle } = useTheme();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  return (
    <div className="flex min-h-full">
      <aside className={cx("fixed inset-y-0 left-0 z-40 w-60 shrink-0 border-r border-border bg-surface transition-transform lg:static lg:translate-x-0",
        open ? "translate-x-0" : "-translate-x-full")}>
        <div className="flex h-14 items-center gap-2 border-b border-border px-4">
          <img src="/favicon.svg" alt="" className="h-7 w-7" />
          <div>
            <div className="text-sm font-semibold leading-tight">Maintenix AI</div>
            <div className="text-2xs text-subtle">Predictive maintenance</div>
          </div>
        </div>
        <nav className="space-y-0.5 p-2" aria-label="Main">
          {NAV.filter((n) => !n.admin || can("admin")).map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"} onClick={() => setOpen(false)}
              className={({ isActive }) => cx("flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm",
                isActive ? "bg-primary/10 font-medium text-primary" : "text-subtle hover:bg-muted hover:text-fg")}>
              <Icon d={n.icon} />{n.label}
            </NavLink>
          ))}
        </nav>
        <div className="absolute inset-x-0 bottom-0 border-t border-border p-3 text-2xs text-subtle">
          Advisory system. Predictions never control equipment.
        </div>
      </aside>
      {open && <div className="fixed inset-0 z-30 bg-black/30 lg:hidden" onClick={() => setOpen(false)} />}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 items-center justify-between gap-2 border-b border-border bg-surface/95 px-4 backdrop-blur">
          <button className="btn-ghost lg:hidden" aria-label="Open navigation" onClick={() => setOpen(true)}>☰</button>
          <div className="flex-1" />
          <button className="btn-ghost" onClick={toggle} aria-label="Toggle colour theme" title="Toggle theme">{theme === "dark" ? "☀" : "☾"}</button>
          <div className="hidden text-right sm:block">
            <div className="text-sm font-medium leading-tight">{user?.full_name}</div>
            <div className="text-2xs capitalize text-subtle">{user?.role}</div>
          </div>
          <button className="btn-secondary" onClick={async () => { await logout(); nav("/login"); }}>Sign out</button>
        </header>
        <main className="mx-auto w-full max-w-[1400px] flex-1 p-4 sm:p-6"><Outlet /></main>
      </div>
    </div>
  );
}
