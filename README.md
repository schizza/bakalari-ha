# Bakaláři for HomeAssistant

[![CI](https://img.shields.io/github/actions/workflow/status/schizza/bakalari-ha/ci.yml?branch=main)](https://github.com/schizza/bakalari-ha/actions) [![Validate](https://img.shields.io/github/actions/workflow/status/schizza/bakalari-ha/validate.yml?label=hassfest%20%26%20HACS&branch=main)](https://github.com/schizza/bakalari-ha/actions) [![HACS Custom](https://img.shields.io/badge/HACS-Custom-blue.svg)](https://hacs.xyz) [![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.8%2B-41BDF5)](https://www.home-assistant.io/) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Custom komponenta pro Home Assistant, založená na [async-bakalari-api3](https://github.com/schizza/async-bakalari-api3), která umožňuje načítání data ze serveru školního systému Bakalářů a integraci s Home Assistantem.

## Komponenta je prozatím v testovacím stavu, jednotlivé služby budou postupně přidávány.

## Instalace (HACS)

1. V HACS → **Integrations** → menu (⋮) → **Custom repositories**
2. URL: `https://github.com/schizza/async-bakalari-ha`, Category: **Integration**
3. Nainstaluj, restartuj HA.
4. **Settings → Devices & Services → Add Integration → "Bakaláři"** a přihlas se.

## Entita

- `sensor.bakalari_new_marks_today` – počet nových známek dnes
  - atributy: `per_subject`, `latest`, `last_sync`

## Požadavky

- Home Assistant `2025.1.4+`
- PyPI: `async-bakalari-api==0.3.7`

## Licence

MIT
