# Provozní runbook

Tento dokument je kontrolní seznam pro společnou konfiguraci po dokončení vývoje.
Neobsahuje žádné skutečné účty, tokeny ani finanční údaje.

## Bezpečnostní hranice

Produkce používá právě dva Vercel projekty:

- `portfolio-app`: Next.js UI, read-only REST a MCP. Zná pouze read-only Neon URL,
  hash hesla vlastníka, session secret a hash MCP bearer tokenu.
- `portfolio-worker`: FastAPI importy a cron. Jako jediný zná write Neon URL,
  master encryption key, Gmail OAuth secret, XTB/George PDF hesla a private Blob token.

Preview prostředí nesmí zdědit produkční databázi, Blob ani secrets. Preview může používat
pouze syntetická data a explicitní `ALLOW_PREVIEW_AUTH_BYPASS=true`.

## Pořadí konfigurace

1. Vytvořit produkční Neon databázi a oddělenou preview/test větev v EU regionu.
2. Aplikovat všechny soubory `migrations/*.sql` v pořadí názvů.
3. Vytvořit dvě přihlašovací role a URL: read-only roli s členstvím
   `portfolio_app` a write roli s členstvím `portfolio_worker`.
4. Založit dva Vercel projekty z tohoto repozitáře:
   - app root `apps/app`;
   - worker root `apps/worker`.
5. Připojit private Vercel Blob pouze k workeru.
6. V Google Cloud vytvořit OAuth klienta s jediným Gmail scope
   `gmail.readonly`; callback nastavit na worker
   `/v1/oauth/gmail/callback`.
7. Nastavit Gmail pravidla jako JSON. Každé pravidlo musí obsahovat zároveň
   omezení `label:` i `from:`; worker širší dotaz odmítne.
8. Vygenerovat nezávislé signing/session/cron/MCP klíče a 32bytový master key.
   Recovery kopii master key uložit do cloudového password manageru.
9. Nakonfigurovat účty, listingy, provider symboly a tři ETF proxy benchmarky
   `SP500`, `MSCI_WORLD`, `MSCI_ACWI`. U každého XTB účtu uložit heslo k PDF;
   u klasického i DIP účtu České spořitelny uložit jako `GEORGE_PDF_PASSWORD`
   čtyřmístný rok narození. Hodnota se zadává pouze do přihlášeného dashboardu.
10. Zapnout Vercel cron workeru a firewall limit pro `/api/session`,
    `/v1/manual/*`, `/v1/import/*` a OAuth callback.
11. Projít první syntetický import, poté reprezentativní dokument každého brokera
    v bezpečném produkčním acceptance testu a nakonec historický backfill. Reálný
    dokument ani jeho textovou extrakci neukládat do GitHubu. U České spořitelny
    zvlášť ověřit zaheslovaný klasický e-mail a ruční DIP import z ChatGPT.
12. Teprve po úspěšném smoke testu přepnout produkční DNS.

CI i produkční build používají committed `pnpm-lock.yaml` a `apps/worker/uv.lock` ve frozen režimu.
Úplný seznam názvů proměnných je v `.env.example`. Hodnoty se nikdy neukládají
do GitHubu ani do proměnných dostupných oběma projektům.

## První datové nastavení

- Každý účet má pseudonym, broker, `DIP` nebo `STANDARD` a základní měnu.
- Každý obchodovatelný instrument má ověřené ISIN, právní typ, ekonomickou
  asset class a alespoň jeden listing.
- `listing.provider_symbols` mapuje poskytovatele na symbol, například
  `{"twelve_data":"VWCE:XETR","alpha_vantage":"VWCE.DEX"}`.
- Proxy benchmark je databázová konfigurace, nikoli kódová konstanta.
- Neznámá klasifikace se nezahazuje; expozice ji vrací jako `Unknown` a snižuje
  coverage.

## Ověření po nasazení

1. `GET /health` workeru vrátí pouze technický stav bez secretů.
2. Nepřihlášený dashboard a REST vrátí 401 nebo login; přihlášení nastaví
   HttpOnly, Secure a SameSite=Strict cookie.
3. MCP bez bearer tokenu odmítne požadavek a s tokenem nabízí deset read-only
   analytických tools a jediný write tool `import_george_dip_statement`. Pokus
   použít jej pro jiného brokera nebo účet bez `DIP` worker odmítne.
4. Ruční sync vytvoří `job_run`, opakování stejného importu nezvýší počet
   ledger událostí a chyba neobsahuje dokument ani secret.
5. Denní job vytvoří CZK i EUR position/portfolio/exposure snapshots,
   benchmark series, quality issues a šifrovanou zálohu.
6. Dashboard zobrazuje odděleně Vše/DIP/Klasické, freshness a `Unknown` coverage.
7. App role nedokáže číst `encrypted_secret`, `secret_access_audit` ani
   `raw_import` a nemá INSERT/UPDATE/DELETE.
8. Worker endpointy odmítnou neplatný podpis, prošlý timestamp a nesprávný cron secret.

## Backup a restore drill

Zálohy jsou před odesláním do private Blob komprimované a šifrované AES-GCM.
Denní sloty rotují po sedmi dnech a týdenní po čtyřech týdnech.

Restore drill se vždy provádí do nové izolované Neon větve:

1. Vytvořit prázdnou větev, aplikovat stejné migrace a ověřit jejich checksumy.
2. Z private Blob stáhnout vybraný `.json.gz.enc` objekt bez jeho zveřejnění.
3. Ve worker prostředí se stejnou verzí master key zavolat
   `EncryptedArchive.decode_backup(pathname=..., payload=...)`.
4. Importovat tabulky v referenčním pořadí uvedeném v
   `WorkerRepository.export_backup_tables`; nikdy nepřepisovat produkci.
5. Spustit databázový integrační test, přepočítat poslední snapshots a porovnat
   počty raw importů, ledger events, lots, secrets a poslední hodnotu portfolia.
6. Přihlásit testovací app proti restore větvi, ověřit REST/MCP a výsledek
   zaznamenat bez finančních hodnot.
7. Restore větev po schválení bezpečně odstranit podle retenční politiky Neonu.

Samotné dešifrování a validace formátu jsou součástí automatických testů.
První skutečný restore drill provedeme společně při produkční konfiguraci.

## Incidenty a rotace

- Při úniku app secretu rotovat session/MCP/signing klíče; master key se nemění.
- Při podezření na únik master key zastavit worker, zneplatnit Blob token,
  vytvořit nový key version, znovu zašifrovat dynamické secrets a zálohy a
  zaznamenat audit.
- Při chybě parseru ponechat raw import v review/error stavu. Oprava vytváří
  reversal a novou událost, nemaže append-only ledger.
- Při chybě cen/FX se nezobrazuje falešná nula: snapshot je missing/partial a
  vznikne data-quality issue.
- Gmail a price providery mají checkpointy a překryvné okno; bezpečné opakování
  je očekávaný recovery mechanismus.
