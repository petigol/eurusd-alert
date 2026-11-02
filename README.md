# EUR/USD Trading Central → ntfy.sh (GitHub Actions)

## Beállítás
1. Hozz létre egy **privát** GitHub repositoryt.
2. Töltsd fel a csomag tartalmát a repository gyökerébe, a `.github/workflows/eurusd.yml` fájllal együtt (a rejtett `.github` mappa fontos).
3. GitHub: **Settings → Secrets and variables → Actions → New repository secret**.
   - Név: `NTFY_TOPIC`
   - Érték: `ict-trade-alert-8k4pck`
4. GitHub: **Settings → Actions → General → Workflow permissions**: válaszd a **Read and write permissions** opciót (a duplikált értesítések elkerüléséhez szükséges állapotfájl mentéséhez).
5. **Actions → EURUSD ntfy monitor → Run workflow**. Ellenőrizd a futási naplót és az ntfy appot.
6. A workflow hétköznapokon 15 percenként van ütemezve (UTC, GitHub terhelés miatt késhet). A GitHub ütemezés nem garantált valós idejű.

## Fontos korlátok
- A monitor **új/megújult EUR/USD szintkombinációkról** küld ntfy értesítést.
- **Belépésizóna-riasztást egyelőre NEM küld**: a TradingKey cikkek megjelenített publikációs idejének időzónája nincs függetlenül igazolva. Elavult jelzésből nem generálunk megtévesztő R/R riasztást.
- A script tartalmaz friss árfolyamlekérdezőt (Yahoo Finance), de ezt csak az időbélyeg és a kereskedési logika ellenőrzése után kapcsoljuk össze a belépésizóna-figyeléssel.
- A TradingKey HTML-je vagy hozzáférési szabályai változhatnak. HTTP 403/429 vagy robots.txt tiltás esetén a program leáll; nem kerül megkerülésre hozzáféréskorlátozás.
- A nyilvános ntfy témát a téma nevének ismeretében más is olvashatja. Ne küldj rá bizalmas adatot.
- A GitHub Actions használatára a GitHub kvótái és szabályai érvényesek. Nem garantált, hogy minden futás időben indul.
- **Nem köt automatikusan, és nem befektetési ajánlás.**

## Próbaüzenet
A számítógépeden PowerShellből (a nyilvános témára):

```powershell
Invoke-RestMethod -Uri 'https://ntfy.sh/ict-trade-alert-8k4pck' -Method Post -Body 'EUR/USD ntfy teszt - sikeres kapcsolat'
```

## További fejlesztés
1. TradingKey `datePublished`/szerver időbélyeg időzónájának hiteles ellenőrzése.
2. Broker-közeli bid/ask feed és 15 percnél frissebb árfolyam.
3. 2:1 R/R zónába lépéskor egyszeri push, és állapotkövetés.
