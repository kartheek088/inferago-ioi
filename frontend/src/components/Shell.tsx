import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { Compass, FileSearch, Home, KanbanSquare, Moon, Send, Settings, Sun, Users } from "lucide-react";
import { cn } from "../lib/format";

export const NAV = [
  { to: "/", label: "Home", icon: Home },
  { to: "/discover", label: "Discover", icon: Compass },
  { to: "/prospects", label: "Prospects", icon: Users },
  { to: "/research", label: "Research", icon: FileSearch },
  { to: "/outreach", label: "Outreach", icon: Send },
  { to: "/pipeline", label: "Sales Pipeline", icon: KanbanSquare },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function useTheme(): [boolean, () => void] {
  const [dark, setDark] = useState(() => { try { return localStorage.getItem("ioi_theme") !== "light"; } catch { return true; } });
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try { localStorage.setItem("ioi_theme", dark ? "dark" : "light"); } catch { /* ignore */ }
  }, [dark]);
  return [dark, () => setDark((d) => !d)];
}

export function Shell({ children, status }: { children: ReactNode; status?: ReactNode }) {
  const [dark, toggle] = useTheme();
  const loc = useLocation();
  return (
    <div className="flex min-h-full">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-border bg-surface px-3 py-5 md:flex">
        <div className="px-3">
          <div className="flex items-baseline gap-2"><span className="text-lg font-semibold tracking-tight">Inferago</span><span className="rounded-md bg-brand-soft px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-brand">IOI</span></div>
          <div className="mt-0.5 text-xs text-subtle">Sales workspace · Chennai</div>
        </div>
        <nav className="mt-6 flex flex-1 flex-col gap-1" aria-label="Main">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"}
              className={({ isActive }) => cn("relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium no-underline transition-colors hover:no-underline",
                isActive ? "bg-brand-soft text-brand before:absolute before:-left-3 before:top-1.5 before:h-6 before:w-1 before:rounded-r-full before:bg-brand" : "text-subtle hover:bg-muted hover:text-fg")}>
              <n.icon className="h-4 w-4" aria-hidden />{n.label}
            </NavLink>
          ))}
        </nav>
        <div className="space-y-2 border-t border-border px-1 pt-3">
          <div className="flex items-center justify-between px-2 text-xs text-subtle"><span>System</span>{status}</div>
          <button onClick={toggle} className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-sm text-subtle hover:bg-muted" aria-label="Toggle dark mode">
            {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}{dark ? "Light mode" : "Dark mode"}
          </button>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center justify-between border-b border-border bg-surface/90 px-4 py-3 backdrop-blur md:hidden">
          <span className="font-semibold">Inferago</span>
          <div className="flex items-center gap-2">{status}<button onClick={toggle} className="rounded p-2 text-subtle" aria-label="Toggle dark mode">{dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}</button></div>
        </header>
        <main key={loc.pathname} className="mx-auto w-full max-w-6xl flex-1 px-4 pb-24 pt-6 sm:px-6 md:pb-10">{children}</main>
        <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-7 border-t border-border bg-surface md:hidden" aria-label="Main mobile">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"}
              className={({ isActive }) => cn("flex flex-col items-center gap-0.5 py-2 text-[10px] no-underline hover:no-underline", isActive ? "text-brand" : "text-subtle")}>
              <n.icon className="h-5 w-5" aria-hidden />{n.label.replace("Sales ", "").replace("Prospects", "Leads")}
            </NavLink>
          ))}
        </nav>
      </div>
    </div>
  );
}
