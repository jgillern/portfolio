import { Navigation } from "@/components/Navigation";
import { requireOwner } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function DashboardLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  await requireOwner();
  return (
    <div className="app-shell">
      <Navigation />
      <main className="main-content">
        {process.env.DATA_MODE !== "database" ? (
          <div className="demo-banner">
            <span>Ukázkový režim</span>
            Veškerá zobrazená čísla jsou syntetická.
          </div>
        ) : null}
        {children}
        <footer className="site-footer">
          Analytický a evidenční nástroj. Nejde o investiční ani daňové poradenství.
        </footer>
      </main>
    </div>
  );
}
