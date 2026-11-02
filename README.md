# EUR/USD Trading Central → GitHub Actions → ntfy

A monitor 15 percenként ütemezve ellenőrzi a TradingKey EUR/USD intraday elemzését és a Yahoo EURUSD egyperces gyertyájának utolsó nem üres záróárát. A GitHub ütemezés késhet, nem garantál pontos negyedórás indulást.

A meglévő `NTFY_TOPIC` Actions Secretet használja. Titkos értéket ne írj fájlba vagy naplóba.

## Publikáció és árfolyam

A publikáció UTC-ideje a cikk saját `window.__QUDE_LOADER_DATA__` adatai közül származik: egyező cikkazonosító, EURUSD, INTRADAY és Unix `publishAt`. Az első észlelés külön megfigyelési adat, soha nem publikációs bizonyíték. Hiányzó időbélyeg vagy 24 óránál régebbi elemzés esetén nincs belépési jelzés.

Legfeljebb 5 perces árfolyam fogadható el; a több mint 60 másodperccel jövőbeli időbélyeg és hibás ár elutasítva. A Yahoo késleltetett/indikációs forrás, nem végrehajtható bid/ask jegyzés. Hozzáférési vagy frissességi hiba esetén a futás naplózza a hiányt, és nem küld belépési jelzést.

## Értesítések

Új cikkről vagy azonos cikk megváltozott irányáról/szintjeiről egyszeri jelzés. Belépési jelzés akkor, ha az ár a pivot és TP1 között van, a pivotig számolt kockázat legalább 3 pip, és a TP1-ig számolt hozam/kockázat legalább 2:1. A pivot feltételezett stop; a spread és csúszás nincs levonva, így a tényleges arány kisebb lehet.

Az állapot a `state.json` fájlban marad meg, a futások sorban futnak. Sikeres küldés után az állapot rögtön helyben mentésre kerül, az Actions hibás futás után is megpróbálja feltölteni. Ha a küldés és az állapot tartós mentése között megszakad a folyamat, ismétlés előfordulhat: pontosan egyszeri kézbesítés nem garantálható. ntfy HTTP-siker a szerver átvételét igazolja, nem a telefonos megjelenést.

## Tesztelés

`python -m unittest -v` — publikáció cikkazonossága, ismeretlen publikáció blokkolása, ismételt futások és új cikk azonos szintekkel, elavult/jövőbeli/hibás árfolyamok.

A módosítások push után automatikus ellenőrzést indítanak, vagy Actions → Run workflow. Valódi kereskedést nem indít.

A korábbi README nyilvános témanevet tartalmazott. Eltávolítása nem törli a git előzményből; ha ez a használt téma, annak neve korábban nyilvánossá vált.
