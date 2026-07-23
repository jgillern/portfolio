# ADR 0006: Omezený import výpisu z ChatGPT

- Stav: accepted
- Datum: 2026-07-23

## Kontext

Česká spořitelna umí automaticky zasílat výpisy pouze pro klasické portfolio.
DIP účet proto potřebuje ruční aktualizaci. Uživatelsky nejjednodušší cesta je
přiložit PDF do běžného chatu, ve kterém je zapnutá soukromá Portfolio app.

Původní bezpečnostní pravidlo povolovalo MCP jen read-only analytiku. Obecný
zápis z AI zůstává nepřijatelný, ale samotné předání brokerova dokumentu do
stejného idempotentního importního pipeline má podstatně menší a přesně
vymezitelný dopad.

## Rozhodnutí

MCP publikuje jediný write tool `import_george_dip_statement`.

- Vstupem je pseudonym nakonfigurovaného účtu a právě jeden PDF file param
  deklarovaný přes `_meta["openai/fileParams"]`.
- App přijme maximálně 10 MB, vyžaduje HTTPS dočasnou URL, odmítne zjevné
  lokální/private cíle, nestahuje redirecty a ověří podpis `%PDF-`.
- App předá původní bytes podepsaným interním požadavkem workeru a nepersistuje
  je.
- Worker nezávisle ověří `broker = GEORGE`, `tax_wrapper = DIP`,
  `source_channel = CHATGPT` a MIME `application/pdf`.
- Heslo k PDF je uloženo per účet jako `GEORGE_PDF_PASSWORD`, zašifrované
  AES-256-GCM. Master key a plaintext heslo jsou dostupné pouze workeru.
- Parser účtuje jen sekci provedených transakcí. Podané a dosud neprovedené
  pokyny nikdy nevytvoří ledger event.
- Zdrojový fingerprint zajišťuje, že opakované nahrání téhož PDF nemá další
  účinek.
- Původní PDF se archivuje pouze šifrovaně v private Blobu; reálné dokumenty
  ani extrahovaný text nepatří do GitHubu.

Descriptor má `readOnlyHint=false`, `destructiveHint=false`,
`idempotentHint=true` a `openWorldHint=false`. Tyto anotace pomáhají
ChatGPT vysvětlit dopad a řídit schválení, nejsou však bezpečnostní kontrolou;
autorizaci a omezení vždy vynucuje server.

## Důsledky

Read-only analytické tools a databázová read role zůstávají beze změny.
Nevzniká obecný write endpoint, SQL tool, možnost opravovat ledger ani zadávat
brokerovi pokyny. Ruční import z dashboardu zůstává jako fallback.

Při produkční konfiguraci je nutný acceptance test s původním zaheslovaným PDF.
Syntetický test pokrývá známé rozložení ukázky, ale veřejný repozitář nesmí
obsahovat uživatelův dokument ani osobní údaje.

## Reference

- [OpenAI Apps SDK: file handling](https://developers.openai.com/apps-sdk/build/mcp-server#file-handling)
- [OpenAI Apps SDK: annotations](https://developers.openai.com/apps-sdk/reference#annotations)
