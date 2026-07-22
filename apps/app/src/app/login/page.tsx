import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { isOwnerAuthenticated } from "@/lib/auth";

export const metadata: Metadata = { title: "Přihlášení" };
export const dynamic = "force-dynamic";

export default async function LoginPage(): Promise<React.ReactNode> {
  if (await isOwnerAuthenticated()) redirect("/");
  return (
    <main className="login-page">
      <section className="login-card">
        <div className="login-brand">
          <span className="brand-mark" aria-hidden="true">P</span>
          <span>
            <strong>Portfolio</strong>
            <small>read-only analytika</small>
          </span>
        </div>
        <div>
          <p className="eyebrow">Soukromý přístup</p>
          <h1>Vítejte zpět.</h1>
          <p className="login-copy">
            Přihlaste se k agregovanému přehledu účtů, výkonu a kvality dat.
          </p>
        </div>
        <form action="/api/session" method="post" className="login-form">
          <label>
            <span>Heslo</span>
            <input
              autoComplete="current-password"
              autoFocus
              name="password"
              placeholder="••••••••••••"
              required
              type="password"
            />
          </label>
          <button type="submit">Otevřít portfolio</button>
        </form>
        <p className="login-security">Session cookie je podepsaná, HTTP-only a SameSite Strict.</p>
      </section>
      <div className="login-art" aria-hidden="true">
        <div className="orb orb-one" />
        <div className="orb orb-two" />
        <div className="login-quote">
          <span>Auditovatelná historie</span>
          <strong>Každé číslo má původ, čas a kvalitu.</strong>
        </div>
      </div>
    </main>
  );
}
