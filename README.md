# Bakaláři for HomeAssistant

[![CI](https://img.shields.io/github/actions/workflow/status/schizza/bakalari-ha/ci.yml?branch=main)](https://github.com/schizza/bakalari-ha/actions) [![Validate](https://img.shields.io/github/actions/workflow/status/schizza/bakalari-ha/validate.yml?label=hassfest%20%26%20HACS&branch=main)](https://github.com/schizza/bakalari-ha/actions) [![HACS Custom](https://img.shields.io/badge/HACS-Custom-blue.svg)](https://hacs.xyz) [![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.8%2B-41BDF5)](https://www.home-assistant.io/) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![GitHub Downloads](https://img.shields.io/github/downloads/schizza/bakalari-ha/total?label=downloads%20%28all%20releases%29)
![Latest release downloads](https://img.shields.io/github/downloads/schizza/bakalari-ha/latest/total?label=downloads%20%28latest%29)

Custom komponenta pro Home Assistant, založená na [async-bakalari-api3](https://github.com/schizza/async-bakalari-api3), která umožňuje načítání data ze serveru školního systému Bakalářů a integraci s Home Assistantem.

## Komponenta je prozatím v testovacím stavu, jednotlivé služby budou postupně přidávány

## 🚨 Breaking changes

- Verze 1.3.0 zavádí pro každý předmět jednotlivý senzor (dynamické generování podle dat z Bakalářů).
  - původní senzor `all_marks` již drží jen metadata pro Lovelace kartu
  - obsah metadat a co lze z tohoto senzoru získat viz níže.

Od verze 1.1.0 jsou již senzory migrovány pod `DeviceRegistry`
 - nově je každé dítě jako separátní `DeviceRegistry` (zařízení v HUBu) s jednotlivými senzory
 - `uid` senzoru se nezměnilo, ale změnil se název senzoru - nyní dědí jméno z `DeviceRegistry`
   - nově jsou tedy názvy senzorů takto: `sensor.<device_name>_<sensor_name>`
   - kde `<device_name>` je jméno dítěte + škola
   - `friendly_name` je složen z `<sensor_name> - <short_name>`, tedy např. `Rozvrh - Jan`

 - staré senzory se již neaktualizují a nebudou generovány při odebrání a znovupřidání integrace.

  ## ⚠️ ***Po aktualizaci na verzi 1.1.0+ je tedy nutné změnit názvy senzorů v kartách v Lovelace***

## Instalace (HACS)

1. V HACS → **Integrations** → menu (⋮) → **Custom repositories**
2. URL: `https://github.com/schizza/bakalari-ha`, Category: **Integration**
3. Nainstaluj, restartuj HA.
4. **Settings → Devices & Services → Add Integration → "Bakaláři"**, tím se komponenta nainstaluje a stáhne se do cahce seznam škol.
5. V nastavení integrace se pak přidavají jednotlivé děti.

## Senzor

- Zprávy
  - tento senzor stahuje zprávy za poslední měsíc
  - TODO: všechny zprávy za školní rok - problém je v limitu pro `recorder`\
  v plánu je lokální cache, aby se "nezatěžoval" senzor

- Rozvrh
  - tento senzor stahuje rozvrh na aktuální týden +- 7 dní

- Známky
  - každý předmět má nyní svůj vlastní senzro
  - původní senzor `all_marks` udržuje pouze metadata pro Lovelace kartu
  - ze školního serveru se již stahují všechny známky, zrušen limit 30 posledních
  - známky jsou agregované per-předmět a per-child
  - zobrazení poslední přijaté známky nadále funguje bez rozdílu
  - přidána možnost `fire_event` pro vyvolání události při nové známce, bude sloužit k oznámení např. v mobilní aplikaci
  - přidána možnost Websocketu
  - další funkcionality v následujících verzích

Příklad metadat v senzoru `Všechny známky`

```yaml
friendly_names:
  - Český jazyk a literatura
  - Matematika
  ...
mapping_names:
  "2":
    name: Český jazyk a literatura
    abbr: ČJ
  "10":
    name: Matematika
    abbr: M
sensor_map:
  "2": >-
    sensor.bakalari_...._znamky_cj_jméno_dítěte
  "10": >-
    sensor.bakalari_...._znamky_m_jméno_dítěte
summary:
  wavg: "1.22"
  avg: "1.16"
  subjects: "8"
  total_marks: "105"
  total_point_marks: "0"
  total_non_point_marks: "105"
```

## Anotované známky (is_new) a události

- Každá známka je při zpracování anotovaná příznakem `is_new`. Ten je `true`, pokud kombinace (dítě, id známky) ještě nebyla v interní cache integrace.
- Tento příznak používají senzory pro výpočet počtu nových známek a agregace po předmětech.
- Cache „seen“ je in-memory. Po restartu HA se nově načtené známky dočasně považují za nové, dokud je integrace nevyhodnotí a neodpálí události. Pokud potřebuješ trvalé chování přes restarty, je vhodné použít automatizace (viz níže) a/nebo budoucí perzistenci.

### Událost `bakalari_new_mark`

- Při objevení nové známky integrace vyvolá událost `bakalari_new_mark` na Event Busu.
- Payload obsahuje atributy známky dle Bakalářů (např. `id`, `date`, `subject_id`, `subject_abbr`, `subject_name`, `caption`, `theme`, `mark_text`, `is_points`, …).

### Příklad automatizace (oznámení o nové známce)

```yaml
alias: Bakaláři – nová známka (notifikace)
description: Odeslat push notifikaci při nové známce
mode: parallel
trigger:
  - platform: event
    event_type: bakalari_new_mark
condition: []
action:
  - service: notify.mobile_app_telefon
    data:
      title: "Nová známka – {{ trigger.event.data.subject_abbr or trigger.event.data.subject_name }}"
      message: >-
        {{ (trigger.event.data.date | as_datetime).strftime('%-d. %-m. %Y') if trigger.event.data.date else '' }}
        {{ trigger.event.data.caption or 'Hodnocení' }}:
        {{ trigger.event.data.mark_text }}
      data:
        url: /lovelace/bakalari
```

## Události pro zprávy (Komens)

- Zprávy jsou také anotované příznakem `is_new`. Integrace udržuje in-memory cache již „viděných“ zpráv per dítě.
- Při objevení nové zprávy se odpálí událost `bakalari_new_message`.

Payload:
```yaml
child_key: <kompozitní klíč dítěte>
message: <plný objekt zprávy z Bakalářů>
```

Příklad automatizace (notifikace):
```yaml
alias: Bakaláři – nová zpráva (notifikace)
mode: parallel
trigger:
  - platform: event
    event_type: bakalari_new_message
action:
  - service: notify.mobile_app_telefon
    data:
      title: "Nová zpráva – {{ trigger.event.data.message.subject or trigger.event.data.message.title }}"
      message: >-
        {{ (trigger.event.data.message.date | as_datetime).strftime('%-d. %-m. %Y') if trigger.event.data.message.date else '' }}
        {{ trigger.event.data.message.preview or trigger.event.data.message.title }}
      data:
        url: /lovelace/bakalari
```

## Služby

- `bakalari.mark_as_seen`
  - Parametry: `mark_id` (povinné), `child_key` (volitelné – pokud není, použije se první dítě).
  - Popis: Označí známku jako „viděnou“ a potlačí její opětovné hlášení jako novou.

- `bakalari.refresh`
  - Popis: Okamžitě obnoví data známek (jinak běží podle intervalu).

- `bakalari.mark_message_as_seen`
  - Parametry: `message_id` (povinné), `child_key` (volitelné).
  - Popis: Označí zprávu jako „viděnou“ a potlačí její opětovné hlášení jako novou.

- `bakalari.refresh_messages`
  - Popis: Okamžitě obnoví data zpráv.

- `bakalari.refresh_timetable`
  - Popis: Okamžitě obnoví data rozvrhu.

Příklady volání:
```yaml
service: bakalari.mark_as_seen
data:
  mark_id: "m123"
  child_key: "john.doe@school|12345"
```

```yaml
service: bakalari.mark_message_as_seen
data:
  message_id: "msg-abc"
```

## WebSocket API

Využij v Dev Tools → WebSocket, nebo z vlastních frontend karet.

- `bakalari/get_marks`
  - Payload: `config_entry_id` (string), `child_key` (volitelné), `limit` (volitelné, default 50)
  - Výsledek: `{ "items": [ ... ] }` – plochý seznam známek s `is_new`.

- `bakalari/get_messages`
  - Payload: `config_entry_id` (string), `child_key` (volitelné), `limit` (volitelné, default 50)
  - Výsledek: `{ "items": [ ... ] }` – seznam zpráv s `is_new`.

- `bakalari/get_timetable`
  - Payload: `config_entry_id` (string), `child_key` (volitelné), `limit` (volitelné, default 3)
  - Výsledek: `{ "items": [ ... ] }` – seznam týdnů rozvrhu (aktuální, +1 týden, -1 týden).

Příklad požadavku/odpovědi:
```json
{ "id": 1, "type": "bakalari/get_marks", "config_entry_id": "<entry_id>", "limit": 25 }
```
```json
{ "id": 1, "type": "result", "success": true, "result": { "items": [ /* ... */ ] } }
```

## Intervaly dotazování

- Známky: klíč `scan_interval` (sekundy), výchozí 900 s. Probíhá s jitterem ±10 % kvůli omezení špiček.
- Zprávy: klíč `scan_interval_messages` (sekundy), výchozí 3600 s. Také s jitterem ±10 %.
- Rozvrh: klíč `scan_interval_timetable` (sekundy), výchozí 21600 s (6 h). Také s jitterem ±10 %.

Poznámky:
- Intervaly se aplikují per koordinátor. Pokud nejsou klíče v options přítomné, použijí se výchozí hodnoty.
- Po ručním volání služeb `refresh*` se naplánuje další cyklus opět podle intervalu.

## Karty pro Lovelace jsou nyní instalovány přes HACS ve vlastím [repozitáři](https://github.com/schizza/bakalari-ha-frontend).

- v HACS přidej repozitář `https://github.com/schizza/bakalari-ha-frontend`
  - typ: `Ovládací panel`
  - nainstaluj poslední verzi
  - pak lze do Lovelace přidat vlastní kartu dle požadovaného typu
    - Zprávy `type: custom:bakalari-messages-card`
  - více informací o kartách najdete v [repozitáři](https://github.com/schizza/bakalari-ha-frontend)

## Přehled senzorů a atributů

Níže je stručný přehled vytvářených entit a jejich stavů/atributů.

- Nové známky – `sensor.Nové známky - <dítě>`
  - Stav: počet nových známek (počítá se podle příznaku is_new u každé známky)
  - Atributy:
    - `child_key`: identifikátor dítěte
    - `recent`: posledních několik známek (každá položka nese alespoň: `id`, `date`, `subject_id`, `subject_abbr`, `subject_name`, `caption`, `theme`, `mark_text` nebo `points_text`, `is_points`, případně `weight/coef/coefficient`, a hlavně `is_new`)
    - `total_marks_cached`: kolik známek je právě v cache koordinátoru

- Poslední známka – `sensor.Poslední známka - <dítě>`
  - Stav: krátký text „<předmět> <známka>“, např. „M 1“
  - Atributy:
    - `child_key`: identifikátor dítěte
    - `last`: poslední známka (stejná struktura položky jako výše)

- Známky podle předmětu – `sensor.Známky <ABBR> - <dítě>` (dynamicky generované per předmět)
  - Stav: počet známek v daném předmětu
  - Atributy:
    - `child_key`: identifikátor dítěte
    - `subject_key`: interní klíč předmětu (id nebo zkratka či jméno)
    - `subject`: agregované statistiky pro předmět:
      - `count`, `new_count`, `numeric_count`, `non_numeric_count`
      - `avg` (aritmetický průměr), `wavg` (vážený průměr)
      - `last_text`, `last_date` (poslední známka a datum)
    - `recent`: poslední známky pro daný předmět (položky se stejnou strukturou jako výše)

- Pomocný index – `sensor.Všechny známky - <dítě>`
  - Stav: počet předmětů pro dané dítě (celkem)
  - Atributy:
    - `friendly_names`: seznam názvů předmětů
    - `mapping_names`: mapování ID → `{ name, abbr }`
    - `sensor_map`: mapování `subject_key` → `entity_id` příslušné senzorové entity
    - `summary`: souhrnné statistiky ze zdroje (např. `wavg`, `avg`, `subjects`, `total_marks`, `total_point_marks`, `total_non_point_marks`)

- Zprávy – `sensor.Zprávy - <dítě>`
  - Stav: počet zpráv v cache
  - Atributy:
    - `child_key`: identifikátor dítěte
    - `messages`: seznam zpráv (každá zpráva je anotovaná `is_new`)
    - `total_messages_cached`: počet zpráv v cache

- Rozvrh – `sensor.Rozvrh - <dítě>`
  - Stav: počet dostupných týdnů rozvrhu v cache
  - Atributy: obsahuje zestručněné informace o rozvrhu dle dostupných dat koordinátoru rozvrhu

- Rozvrh – kalendářová entita `calendar.Rozvrh - <dítě>`
  - Zobrazuje jednotlivé hodiny v daném období (aktuální týden, +1 a -1 týden)
  - Vlastnosti událostí: `start`, `end`, `summary` (předmět), `description` (učitel, skupiny, téma, změny), `location` (učebna)

Poznámky:
- Každá známka i zpráva je anotovaná příznakem `is_new` (in-memory per dítě). Po restartu HA se nové položky mohou dočasně chovat jako „nové“, dokud proběhne první diff.
- Pro potlačení „novosti“ lze použít služby `bakalari.mark_as_seen` a `bakalari.mark_message_as_seen` (viz výše).

## Datové modely v koordinátorech

Tyto struktury najdeš v `coordinator.data`. Klíče jsou stabilní API pro senzory, frontend karty a automatizace.

- Koordinátor známek
  - `subjects_by_child`: mapování `child_key` → `{ <subject_id>: { id, name, abbr }, ... }`
  - `marks_by_child`: mapování `child_key` → `list[mark]` – už anotované položky s `is_new`
  - `marks_flat_by_child`: mapování `child_key` → `list[mark]` – „surové“ položky (bez `is_new`), používá se pro diff a eventy
  - `summary`: mapování `child_key` → souhrnné statistiky (např. `wavg`, `avg`, `subjects`, `total_marks`, `total_point_marks`, `total_non_point_marks`)
  - `school_year`: `{ start: ISO date, end_exclusive: ISO date }`
  - `last_sync_ok`: boolean
  - Položka `mark` typicky obsahuje: `id`, `date`, `subject_id`, `subject_abbr`, `subject_name`, `caption`, `theme`, `mark_text` nebo `points_text`, `is_points`, případně `weight/coef/coefficient`, a v anotované větvi navíc `is_new`.

- Koordinátor zpráv (Komens)
  - `messages_by_child`: mapování `child_key` → `list[message]` – každá zpráva má `is_new`
  - `last_sync_ok`: boolean
  - Položka `message` je slovník dle API (např. `id`/`message_id`, `title`/`subject`, `date`/`created`, `preview`, `from`, `to`, …) + `is_new`.

- Koordinátor rozvrhu
  - `timetable_by_child`: mapování `child_key` → `list[week]` – aktuální týden, +1 týden, -1 týden
  - `permanent_timetable_by_child`: mapování `child_key` → „permanentní“ rozvrh (pokud škola poskytuje)
  - `timetable_window_dates`: mapování `child_key` → `list[ISO date]` – jaké dny byly načteny
  - `last_sync_ok`: boolean

Doporučení:
- Pro zobrazování použij `marks_by_child` (již obsahuje `is_new`), pro odvozování novinek v automatizacích se spolehni na události `bakalari_new_mark` a `bakalari_new_message`.
- Per-předmět agregace a další statistiky pro senzory poskytuje helper `aggregate_marks_for_child` a jsou k dispozici v atributech senzorů dle výše uvedeného přehledu.

## Screenshot

![Screenshot](https://raw.githubusercontent.com/schizza/bakalari-ha/refs/heads/main/docs/screenshot.png)

## Požadavky

- Home Assistant `2025.9.4+`
- PyPI: `async-bakalari-api==0.8.1`

## Licence

MIT
