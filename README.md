# EUR/USD londoni sweep és MSS

A GitHub Actions meglévő, külső `workflow_dispatch` indítását használja. Az első hétköznapi indítás 02:44–04:00 New York-i idő között figyeli az M5 adatot a londoni ablak végéig. Minden más futás azonnal kilép.

Az előző forexnap határa 17:00 New York-i idő szerint. Hétfőn a pénteken lezárt sávot használja. Teljes előző napi gyertyasor kell. A Yahoo EURUSD=X 5 perces adata indikációs ár. Az utolsó megjelenő gyertyát a program kihagyja, amíg újabb időbélyeg meg nem jelenik. A napló a Yahoo által addig közölt legfrissebb lezárt gyertya korát és siker esetén az ntfy átvételéig eltelt időt rögzíti.

A friss MSS-értesítés a modell szerinti következő nyitás idejét közli. Az észlelést és a küldés indítását 15 másodpercen belül engedi a záráshoz képest. A nyitási ár ezen belül is változhat. Elavult gyertyákból visszaépíti a napi állapotot.

A meglévő `NTFY_TOPIC` Actions Secret szükséges, az `NTFY_SERVER` és az `NTFY_TOKEN` opcionális. A deduplikáció kulcsát publikálás előtt pusholja a repóba. Ha a publikálás hibázik, az esemény már lefoglalva marad, így ugyanarról az eseményről nem küld duplikátumot.

`python3 -m unittest -v` a visszajátszásos tesztekhez. A kódváltozás utáni első workflow-futás TESZT ntfy üzenetet küld és megpróbálja lekérni a Yahoo M5 adatot.
