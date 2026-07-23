const labels: Record<string, string> = {
  healthy: "Aktuální",
  stale: "Zastaralé",
  error: "Chyba",
  not_configured: "Nenastaveno",
  verified: "Ověřeno",
  estimated: "Odhad",
  partial: "Částečné",
  missing: "Chybí",
  open: "Otevřené",
  warning: "Upozornění",
  critical: "Kritické",
};

export function StatusBadge({ value }: { value: string }): React.ReactNode {
  const normalized = value.toLowerCase();
  return (
    <span className={"status status-" + normalized}>
      <span aria-hidden="true" />
      {labels[normalized] ?? value}
    </span>
  );
}
