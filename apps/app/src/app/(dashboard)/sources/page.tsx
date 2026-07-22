import type { Metadata } from "next";

import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { formatDateTime } from "@/lib/format";
import { getAccounts, getDataQualityIssues, getImportStatus } from "@/lib/read-model";

export const metadata: Metadata = { title: "Zdroje dat" };

export default async function SourcesPage(): Promise<React.ReactNode> {
  const [sources, issues, accounts] = await Promise.all([
    getImportStatus(),
    getDataQualityIssues(),
    getAccounts(),
  ]);
  const errors = sources.reduce((total, source) => total + source.error_count, 0);

  return (
    <>
      <PageHeader
        eyebrow="Provoz a audit"
        title="Data sources / Import health"
        description="Čerstvost, duplicity a chyby jsou viditelné; automatizace nikdy neskrývá neúplnost."
        aside={<div className="headline-number"><span>Chyb celkem</span><strong>{errors}</strong></div>}
      />
      <section className="source-grid">
        {sources.map((source) => (
          <article className="panel source-card" key={source.connector}>
            <div className="source-title">
              <div className="source-icon">{source.connector.slice(0, 2)}</div>
              <div><h2>{source.connector.replaceAll("_", " ")}</h2><span>Read-only connector</span></div>
              <StatusBadge value={source.status} />
            </div>
            <dl className="source-stats">
              <div><dt>Poslední kontrola</dt><dd>{formatDateTime(source.last_checked_at)}</dd></div>
              <div><dt>Poslední úspěch</dt><dd>{formatDateTime(source.last_success_at)}</dd></div>
              <div><dt>Importováno</dt><dd>{source.imported_count}</dd></div>
              <div><dt>Duplicity</dt><dd>{source.duplicate_count}</dd></div>
              <div><dt>Chyby</dt><dd>{source.error_count}</dd></div>
            </dl>
          </article>
        ))}
      </section>

      <section className="dashboard-grid source-lower">
        <article className="panel panel-wide">
          <div className="panel-heading"><div><p className="eyebrow">Data quality</p><h2>Otevřená zjištění</h2></div></div>
          {issues.length ? (
            <div className="issue-list">
              {issues.map((issue) => (
                <div key={issue.id}>
                  <StatusBadge value={issue.severity} />
                  <div><strong>{issue.summary}</strong><span>{issue.code} · {formatDateTime(issue.detected_at)}</span></div>
                  <StatusBadge value={issue.status} />
                </div>
              ))}
            </div>
          ) : <div className="empty-state">Žádná otevřená zjištění.</div>}
        </article>
        <article className="panel">
          <div className="panel-heading"><div><p className="eyebrow">Scope</p><h2>Účty</h2></div></div>
          <ul className="account-list">
            {accounts.map((account) => (
              <li key={account.id}><div><strong>{account.name}</strong><span>{account.broker}</span></div><span className="wrapper-pill">{account.tax_wrapper}</span></li>
            ))}
          </ul>
        </article>
      </section>
    </>
  );
}
