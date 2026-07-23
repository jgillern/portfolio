"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

const items = [
  { href: "/", label: "Přehled", glyph: "⌁" },
  { href: "/holdings", label: "Pozice", glyph: "◫" },
  { href: "/transactions", label: "Transakce", glyph: "↕" },
  { href: "/exposures", label: "Expozice", glyph: "◎" },
  { href: "/sources", label: "Zdroje dat", glyph: "◉" },
  { href: "/methodology", label: "Metodika", glyph: "§" },
] as const;

export function Navigation(): React.ReactNode {
  const pathname = usePathname();
  const [leaving, setLeaving] = useState(false);

  async function logout(): Promise<void> {
    setLeaving(true);
    await fetch("/api/session", { method: "DELETE" });
    window.location.assign("/login");
  }

  return (
    <aside className="sidebar">
      <Link className="brand" href="/">
        <span className="brand-mark" aria-hidden="true">P</span>
        <span>
          <strong>Portfolio</strong>
          <small>osobní analytika</small>
        </span>
      </Link>

      <nav className="primary-nav" aria-label="Hlavní navigace">
        {items.map((item) => {
          const active =
            item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          return (
            <Link
              className={active ? "nav-link active" : "nav-link"}
              href={item.href}
              key={item.href}
            >
              <span className="nav-glyph" aria-hidden="true">{item.glyph}</span>
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="sidebar-foot">
        <span className="security-dot" aria-hidden="true" />
        <span>Read-only přístup</span>
        <button className="logout-button" disabled={leaving} onClick={logout} type="button">
          {leaving ? "Odpojuji…" : "Odhlásit"}
        </button>
      </div>
    </aside>
  );
}
