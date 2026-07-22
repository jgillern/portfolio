import type { Metadata } from "next";

import { PageHeader } from "@/components/PageHeader";
import { getMethodology } from "@/lib/read-model";

export const metadata: Metadata = { title: "Metodika" };

export default async function MethodologyPage(): Promise<React.ReactNode> {
  const methodology = await getMethodology();
  const sections = [
    ["Canonical ledger", methodology.ledger],
    ["TWR a XIRR", methodology.performance],
    ["Měnové kurzy", methodology.fx],
    ["Ocenění", methodology.valuation],
    ["ETF proxy benchmarky", methodology.benchmarks],
    ["Expozice a look-through", methodology.exposures],
  ];
  return (
    <>
      <PageHeader
        eyebrow={"Verze metodiky " + methodology.version}
        title="Jak čísla vznikají"
        description="Definice, zdroje a limity jsou součástí výsledku — ne poznámka pod čarou."
      />
      <div className="methodology-layout">
        <aside className="methodology-index">
          <strong>Na této stránce</strong>
          {sections.map(([title], index) => <a href={"#section-" + index} key={title}>{title}</a>)}
          <a href="#limitations">Omezení</a>
        </aside>
        <article className="panel prose">
          {sections.map(([title, body], index) => (
            <section id={"section-" + index} key={title}>
              <span className="method-number">{String(index + 1).padStart(2, "0")}</span>
              <div><h2>{title}</h2><p>{body}</p></div>
            </section>
          ))}
          <section id="limitations">
            <span className="method-number">07</span>
            <div><h2>Omezení</h2><ul>{methodology.limitations.map((item) => <li key={item}>{item}</li>)}</ul></div>
          </section>
        </article>
      </div>
    </>
  );
}
