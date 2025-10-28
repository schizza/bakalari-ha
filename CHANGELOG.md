# Changelog

## v0.2.0 - 2025-10-28

### Co je nového

### ✨ Nové funkce

Implementace `DeviceRegistry` (#60) @schizza

- Přidána podpora `Device Registry` pro komponentu Bakaláři – vytváří zařízení pro každý dětský účet a zpřístupňuje verze knihoven.
  
- zavádí nové služby pro notifikace - nově přijaté známky, vyvolání obnovení dat, atd.
  
- Přidán WebSocket API pro získávání známek a aktualizuje zpracování verzí.
  
- Opravuje https://github.com/schizza/bakalari-ha/issues/46
  
- Přidány senzory známek využívající data z koordinátoru (prozatím pouze poslední přijatá známka)
  
- Implementuje nové senzory pro zobrazení nových a posledních známek každého dítěte
  
- Staré senzory zůstávají kvůli zpětné kompatibilitě a budou odstraněny v budoucí aktualizaci po dokončení migrace.
  

### 🧹 Refaktoring / Údržba

Rozdělení senzorů do samostatných souborů:

- Zlepšuje organizaci a udržovatelnost kódu.
- Zachovává zpětnou kompatibilitu ponecháním starých entit.

### 📝 Dokumentace

Úprava README na aktuální verzi


---

### 📦 Technické

- Verze integrace: `v1.0.0`
- Vyžaduje API verze: `0.5.0`
- Minimální verze Home Assistant: `2025.9+`
- Předchozí tag: `v0.1.1`
- Autoři přispěli: @schizza
