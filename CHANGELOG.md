# # Changelog

## v1.3.1

## ✨ Nové funkce

- Přidány senzory pro jednotlivé předměty
  - Původní senzor `all-marks` nyní drří pouze metadata k senzorům známek pro využití v Lovelace
  - každý senzor pro `Předmět` nyní má svá metadata a drží všechny známky z daného předmětu
  - senzor pro `Předmět` uvádí jako `native_value` celkový počet známek
  - zrušen limit pro 30 posledních známek v předmětu
- Nový `snapshot` API pro známky
  - agregace známek: celkové statistiky (počty, průměr, vážený průměr) a detailní rozpad dle předmětů.
  - Pomocné atributy pro jednodušší využití agregovaných dat.
  - Dynamická tvorba senzorů pro jednotlivé předměty na základě dostupných dat z `Bakalářů`
- Zjednodušené volání API odstraněním generické funkce `_api_call` a zavedením přímých volání knihovny `async_bakalari_api.`
  
## 🐛 Opravy chyb

- ošetřeno generování `unique_id`
- opravena chyba, kdy se senzory generovaly pouze pro poslední díte v seznamu
- aktualizace agregační funkce, aby užívala již získaná data a zabránilo se opětovnému volání `get_items_for_child`

## 🧹 Refaktoring / Údržba

- Nahrazení několika asynchronních volání jediným voláním pro načtení známek (rychlejší a spolehlivější)
- Interní zpracování známek přepracováno tak, aby lépe podporovalo agregace a odvozené informace
- Sledování aktualizací koordinátoru: při objevení nových předmětů se senzory automaticky doplní bez potřeby plného reloadu
- Odstraněn zastaralý kód související s původním způsobem inicializace senzorů
- přidán `basedpyright` do CI kontroly i lokální `make all` kontroly
- přepracováno zpracování agregace známek u podřízených entit, přejmenování a přesunutí agregační funkce, aby byla struktura kódu přehlednější a lépe udržovatelná.
- vylepšeno zpracování událostí kalendáře díky konzistentnímu nakládání s časovými zónami
- ošetření okrajových případů, kdy chyběl koncový čas události. Jako výchozí hodnota je použit čas začátku
- přidány `unity_testy` k ověření `api_calls`
  - správné chování, při chybějící knihovně
  - chyby autentizace
  - obecné chyby
  - serializace `lock`
- logovací zprávy nyní mají název modulu a třídy, což zpřehlední výstup a usnadňuje dohledání původu zprávy

---

## 📦 Technické

- Verze integrace: `v1.3.0`
- Minimální verze Home Assistant: `2025.9+`
- Předchozí tag: `v1.2.0`
- Autoři přispěli: @schizza

## v1.2.0

## ✨ Nové funkce

- Enhances marks data and adds sensors (#71) @schizza
  - Přidán senzor všech námek pro dítě, přidána pre-subject agregace

## 🧹 Refaktoring / Údržba

- bump verze verze API na 0.6.0

---

## 📦 Technické

- Verze integrace: `v1.2.0`
- Vyžaduje API verzi `0.6.0+`
- Minimální verze Home Assistant: `2025.9+`
- Předchozí tag: `v1.1.0`
- Autoři přispěli: @schizza

## v1.1.0

## ✨ Nové funkce

- Migrace všech senzorů pod `coordinator` (#67)
  Refaktoring senzorů, tak aby se pro správu dat používal jen koordinátor.

Tato změna zlepšuje konzistenci dat a snižuje nadbytečné volání API tím, že centralizuje načítání a ukládání dat do mezipaměti.
Do koordinátoru přibyla podpora pro `Zprávy` a `Rozvrh`
Podpora migrace jedinečného ID do nového formátu založeného na ID konfigurační položky a klíči dítěte.

## 🐛 Opravy chyb

**Sensor name** (#68) @schizza

- Aktualizuje názvy senzorů tak, aby obsahovaly zkrácené jméno dítěte.
  Tato změna zlepšuje přehlednost a umožňuje uživatelům snadno rozlišit senzory jednotlivých dětí, pokud je nakonfigurováno více dětí.

**Fixes translations** (#66) @schizza

- Opravuje překlady v češtině

**Fixes usage of deprecated time function** (#65) @schizza

- Funkce `time.time` byla označena jako zastaralá a nahrazena voláním `time()` bez prefixu názvu modulu.

**Improves authentication and logging** (#64) @schizza

- Zlepšuje zpracování autentizace, aby se zabránilo vícenásobným požadavkům na reautorizaci, a vylepšuje logování pro snazší ladění.
  - Přidává zámek, který brání souběžným požadavkům na reautorizaci pro stejné dítě.
  - Zavádí správu stavu pro žádosti o reautorizaci, sleduje, kdy bylo znovupřihlášení vyžádáno.
  - Aktualizuje úrovně logování na „debug“ pro méně ukecaný výstup za běžných okolností a zpřehledňuje logovací zprávy.

**Improves authentication and sensor naming** (#63) @schizza

- Přidává proces reautorizace pro případy, kdy vyprší přihlašovací údaje.
- Vylepšuje názvy senzorů přidáním informací o dítěti pro větší přehlednost.
- Aktualizuje konfiguraci senzorů pro větší konzistenci.

## 🧹 Refaktoring / Údržba

**Improves Bakalari API handling and reauthentication** (#62) @schizza
- Refaktorizace integraci Bakalářů pro zlepšení práce s API, správu tokenů.
  - Implementace centrálního wrapperu pro API volání, která zajišťuje správné zpracování autentizace a chyb.
    - Zavádí proces reautorizace a mechanismus pro resetování tokenu v případě problémů s autentizací.
    - Migrace API endpointů na nový wrapper pro jednotné zpracování chyb a autentizace

---

## 📦 Technické

- Verze integrace: `v1.1.0`
- Vyžaduje API verzi `0.5.0+`
- Minimální verze Home Assistant: `2025.9+`
- Předchozí tag: `v1.0.0`
- Autoři přispěli: @schizza

## 1.0.0

## ✨ Nové funkce

**Implementace `DeviceRegistry`** (#60) @schizza

- Přidána podpora `Device Registry` pro komponentu Bakaláři – vytváří zařízení pro každý dětský účet a zpřístupňuje verze knihoven.
- zavádí nové služby pro notifikace - nově přijaté známky, vyvolání obnovení dat, atd.
- Přidán WebSocket API pro získávání známek a aktualizuje zpracování verzí.
- Opravuje https://github.com/schizza/bakalari-ha/issues/46

- Přidány senzory známek využívající data z koordinátoru (prozatím pouze poslední přijatá známka)
- Implementuje nové senzory pro zobrazení nových a posledních známek každého dítěte
- Staré senzory zůstávají kvůli zpětné kompatibilitě a budou odstraněny v budoucí aktualizaci po dokončení migrace.

## 🧹 Refaktoring / Údržba

**Rozdělení senzorů do samostatných souborů:**
- Zlepšuje organizaci a udržovatelnost kódu.
- Zachovává zpětnou kompatibilitu ponecháním starých entit.

---

## 📦 Technické

- Verze integrace: `v1.0.0`
- Vyžaduje API verze: `0.5.0`
- Minimální verze Home Assistant: `2025.9+`
- Předchozí tag: `v0.1.1`
- Autoři přispěli: @schizza

## 0.1.1

## ✨ Nové funkce

Podpora Rozvrhu `Timetable module`
- V API přidána možnost stažení aktuálního a permanentního rozvrhu.

## Breaking changes

 Karty Lovelace přesunuty do vlastního repozitáře  (schizza/bakalari-ha-frontend)

- smazan www/bakalari-cards.js
- karty pro Lovelace se nyní instalují přes HACS ve vlastním repozitáři

## 🐛 Opravy chyb

- funkce pro `timetable_actual` stahuje v módu dnes +- 7 dní (reálně tedy 3 týdny rozvrhu)

## 🧹 Refaktoring / Údržba

- Fix: Struktura ZIP souboru pro release

- Chore/download counts (#34) (#35) @schizza

  - Enable zip_release for Bakaláři HA
  - Add GitHub Actions workflow for ZIP asset release

Added download badges for total and latest releases.

- Add commitish and filter-by-commitish options
- Update release drafter configuration for versioning
- Add commitish and filter-by-commitish to workflow
- Add initial changelog file
- Add workflow to update CHANGELOG on release

---

## 📦 Technické

- Verze integrace: `v0.1.1`
- Minimální verze Home Assistant: `2025.9+`
- Předchozí tag: `v0.1.0`
- Autoři přispěli: @schizza
