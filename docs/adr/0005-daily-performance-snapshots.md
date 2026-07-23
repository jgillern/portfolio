# ADR 0005: Denní výkonnostní snapshots

- Status: Accepted
- Datum: 2026-07-22

## Kontext

Dashboard potřebuje reprodukovatelné TWR, XIRR, nákladovou bázi, expozice a ETF proxy
benchmarky ve dvou reportovacích měnách. Výpočty za běhu webového requestu by míchaly
různé sady cen a FX kurzů a read-only app by musela získat přístup k citlivějším
ledgerovým tabulkám.

## Rozhodnutí

Worker vytváří pro CZK a EUR denní immutable-input/replaceable-output snapshots:

1. pozice vycházejí výhradně z append-only ledgeru;
2. nákladová báze pro prodeje používá FIFO lots;
3. hotovost je součet cash legs převedených historickým kurzem;
4. externí tok je vklad kladně a výběr záporně; TWR používá jednotnou konvenci toku
   na konci dne;
5. první kvalitní den má kumulované TWR nula, denní TWR není definováno;
6. XIRR používá vklady jako záporné investor cash flow, výběry jako kladné a poslední
   hodnotu jako kladný koncový tok;
7. chybějící cena, FX nebo cost basis se neinterpretuje jako nula, ale snižuje quality;
8. benchmark je konfigurovatelný ETF proxy a normalizuje se proti první dostupné ceně
   od `valid_from`;
9. look-through zachovává nepokrytou váhu jako `Unknown` a publikuje coverage.

App čte pouze snapshots a bezpečné views. Stejný den lze přepočítat idempotentně;
historické ceny a FX zůstávají identifikovatelné přes použité řádky a timestampy.

## Důsledky

- Dashboard a MCP používají konzistentní data bez přístupu k raw importům a secretům.
- Backfill se musí přehrát chronologicky, aby historický FIFO cost basis odpovídal stavu
  v daném dni.
- Pozdější intradenní TWR nebo cash-flow-matched benchmark vyžaduje novou verzovanou
  metodiku, nikoli tichou změnu stávajících snapshots.
