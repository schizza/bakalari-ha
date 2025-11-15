# Bakaláři for HomeAssistant

[![CI](https://img.shields.io/github/actions/workflow/status/schizza/bakalari-ha/ci.yml?branch=main)](https://github.com/schizza/bakalari-ha/actions) [![Validate](https://img.shields.io/github/actions/workflow/status/schizza/bakalari-ha/validate.yml?label=hassfest%20%26%20HACS&branch=main)](https://github.com/schizza/bakalari-ha/actions) [![HACS Custom](https://img.shields.io/badge/HACS-Custom-blue.svg)](https://hacs.xyz) [![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.8%2B-41BDF5)](https://www.home-assistant.io/) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![GitHub Downloads](https://img.shields.io/github/downloads/schizza/bakalari-ha/total?label=downloads%20%28all%20releases%29)
![Latest release downloads](https://img.shields.io/github/downloads/schizza/bakalari-ha/latest/total?label=downloads%20%28latest%29)

Custom komponenta pro Home Assistant, založená na [async-bakalari-api3](https://github.com/schizza/async-bakalari-api3), která umožňuje načítání data ze serveru školního systému Bakalářů a integraci s Home Assistantem.

## Komponenta je prozatím v testovacím stavu, jednotlivé služby budou postupně přidávány

## 🚨 Breaking changes

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

- Rozvrh
  - tento senzor stahuje rozvrh na aktuální týden +- 7 dní

- Známky
  - ze školního serveru se již stahují všechny známky
  - známky jsou agregované per-předmět
  - zobrazení poslední přijaté známky nadále funguje bez rozdílu
  - přidána možnost `fire_event` pro vyvolání události při nové známce, bude sloužit k oznámení např. v mobilní aplikaci
  - přidána možnost Websocketu
  - další funkcionality v následujících verzích

## Karty pro Lovelace jsou nyní instalovány přes HACS ve vlastím [repozitáři](https://github.com/schizza/bakalari-ha-frontend).

- v HACS přidej repozitář `https://github.com/schizza/bakalari-ha-frontend`
  - typ: `Ovládací panel`
  - nainstaluj poslední verzi
  - pak lze do Lovelace přidat vlastní kartu dle požadovaného typu
    - Zprávy `type: custom:bakalari-messages-card`
  - více informací o kartách najdete v [repozitáři](https://github.com/schizza/bakalari-ha-frontend)

## Screenshot

![Screenshot](https://raw.githubusercontent.com/schizza/bakalari-ha/refs/heads/main/docs/screenshot.png)

## Požadavky

- Home Assistant `2025.9.1+`
- PyPI: `async-bakalari-api==0.7.0`

## Licence

MIT
