"use client";

import { useState, type FormEvent } from "react";

import type { AccountSummary } from "@/lib/types";

function brokerCode(name: string): string {
  if (name.includes("George") || name.includes("spořitelna")) return "GEORGE";
  if (name.includes("Patria")) return "PATRIA";
  return "XTB";
}

export function OperationsPanel({
  accounts,
}: {
  accounts: AccountSummary[];
}): React.ReactNode {
  const [message, setMessage] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const passwordAccounts = accounts.filter((account) =>
    ["XTB", "GEORGE"].includes(brokerCode(account.broker)),
  );

  async function connectGmail(): Promise<void> {
    setBusy(true);
    setMessage("");
    const response = await fetch("/api/actions/gmail-oauth", { method: "POST" });
    if (!response.ok) {
      setMessage("Gmail OAuth se nepodařilo zahájit.");
      setBusy(false);
      return;
    }
    const payload = await response.json();
    const url = payload?.data?.authorization_url;
    if (typeof url !== "string") {
      setMessage("Worker nevrátil bezpečnou OAuth adresu.");
      setBusy(false);
      return;
    }
    window.location.assign(url);
  }

  async function sync(): Promise<void> {
    setBusy(true);
    setMessage("");
    const response = await fetch("/api/actions/sync", { method: "POST" });
    setMessage(response.ok ? "Synchronizace byla dokončena." : "Synchronizaci se nepodařilo dokončit.");
    setBusy(false);
  }

  async function upload(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    const form = event.currentTarget;
    const data = new FormData(form);
    const selection = String(data.get("account") ?? "");
    const [broker, accountRef] = selection.split("::", 2);
    data.delete("account");
    data.set("broker_code", broker ?? "");
    data.set("account_ref", accountRef ?? "");
    const response = await fetch("/api/actions/import", { method: "POST", body: data });
    setMessage(response.ok ? "Dokument byl bezpečně zpracován." : "Dokument se nepodařilo zpracovat.");
    if (response.ok) form.reset();
    setBusy(false);
  }

  async function password(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    const form = event.currentTarget;
    const data = new FormData(form);
    const selection = String(data.get("account_secret") ?? "");
    const [secretType, accountId] = selection.split("::", 2);
    const response = await fetch("/api/actions/secret", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        account_id: accountId,
        secret_type: secretType,
        value: data.get("value"),
      }),
    });
    setMessage(response.ok ? "Heslo bylo zašifrováno ve workeru." : "Heslo se nepodařilo uložit.");
    if (response.ok) form.reset();
    setBusy(false);
  }

  return (
    <section className="operations-grid" aria-label="Privilegované operace">
      <article className="panel operation-card">
        <p className="eyebrow">Gmail read-only OAuth</p>
        <h2>Připojit importní schránku</h2>
        <p>Token se po callbacku zašifruje ve workeru a nikdy se nevrací do aplikace.</p>
        <button disabled={busy} onClick={connectGmail} type="button">Připojit Gmail</button>
      </article>

      <article className="panel operation-card">
        <p className="eyebrow">Idempotentní job</p>
        <h2>Synchronizovat nyní</h2>
        <p>Spustí stejný checkpointovaný proces jako denní cron.</p>
        <button disabled={busy} onClick={sync} type="button">Spustit synchronizaci</button>
      </article>

      <article className="panel operation-card">
        <p className="eyebrow">Řízený fallback</p>
        <h2>Nahrát výpis</h2>
        <form onSubmit={upload}>
          <select name="account" required defaultValue="">
            <option disabled value="">Vyberte účet</option>
            {accounts.map((account) => (
              <option key={account.id} value={brokerCode(account.broker) + "::" + account.name}>
                {account.name} · {account.broker}
              </option>
            ))}
          </select>
          <input
            accept=".csv,.html,.htm,.pdf,text/csv,text/html,application/pdf"
            name="document"
            required
            type="file"
          />
          <button disabled={busy} type="submit">Zpracovat dokument</button>
        </form>
      </article>

      <article className="panel operation-card">
        <p className="eyebrow">AES-256-GCM</p>
        <h2>Hesla k PDF výpisům</h2>
        <p>XTB i Česká spořitelna se ukládají odděleně pro každý účet.</p>
        <form onSubmit={password}>
          <select name="account_secret" required defaultValue="">
            <option disabled value="">Vyberte účet</option>
            {passwordAccounts.map((account) => {
              const broker = brokerCode(account.broker);
              const secretType =
                broker === "GEORGE"
                  ? "GEORGE_PDF_PASSWORD"
                  : "XTB_PDF_PASSWORD";
              return (
                <option
                  key={account.id}
                  value={secretType + "::" + account.id}
                >
                  {account.name} · {account.broker}
                </option>
              );
            })}
          </select>
          <input
            autoComplete="new-password"
            name="value"
            placeholder="Heslo se neukládá v aplikaci"
            required
            type="password"
          />
          <button disabled={busy || !passwordAccounts.length} type="submit">Zašifrovat a uložit</button>
        </form>
      </article>
      <p className="operation-message" aria-live="polite">{message}</p>
    </section>
  );
}
