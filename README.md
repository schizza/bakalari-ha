# Bakaláři for HomeAssistant

[![CI](https://img.shields.io/github/actions/workflow/status/schizza/bakalari-ha/ci.yml?branch=main)](https://github.com/schizza/bakalari-ha/actions) [![Validate](https://img.shields.io/github/actions/workflow/status/schizza/bakalari-ha/validate.yml?label=hassfest%20%26%20HACS&branch=main)](https://github.com/schizza/bakalari-ha/actions) [![HACS Custom](https://img.shields.io/badge/HACS-Custom-blue.svg)](https://hacs.xyz) [![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.8%2B-41BDF5)](https://www.home-assistant.io/) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Custom komponenta pro Home Assistant, založená na [async-bakalari-api3](https://github.com/schizza/async-bakalari-api3), která umožňuje načítání data ze serveru školního systému Bakalářů a integraci s Home Assistantem.

## Komponenta je prozatím v testovacím stavu, jednotlivé služby budou postupně přidávány

## Instalace (HACS)

1. V HACS → **Integrations** → menu (⋮) → **Custom repositories**
2. URL: `https://github.com/schizza/bakalari-ha`, Category: **Integration**
3. Nainstaluj, restartuj HA.
4. **Settings → Devices & Services → Add Integration → "Bakaláři"**, tím se komponenta nainstaluje a stáhne se do cahce seznam škol.
5. V nastavení integrace se pak přidavají jednotlivé děti.

## Senzor

- Zprávy
  - tento senzro stahuje zprávy za poslední měsíc

## Přidání karty na dashboard

- v repozitáři stáhněte soubor [bakalari-card.js](https://raw.githubusercontent.com/schizza/bakalari-ha/refs/heads/dev/www/bakalari-card/bakalari-card.js) a umístěte ho do `config/www/bakalari-card/`
- v `Nastavení` -> `Ovládací panely` vyberte vpravo nahoře `⋮` -> `Zdroje`
- Následně `Přidat zdroj`, jako cesta se použije `/local/bakalari-card/bakalari-card.js` a musí být vybraný `Modul JavaScriptu`
- pak lze na dashboard přidat vlastní kartu `Bakalari` s náledujícím nastavením:

```yaml
type: custom:bakalari-card
entity: sensor.bakalari_zpravy_jmeno_ditete
title: 📬 Zprávy pro SuperDítě
```

## Požadavky

- Home Assistant `2025.1.4+`
- PyPI: `async-bakalari-api==0.4.0`

## Licence

MIT
