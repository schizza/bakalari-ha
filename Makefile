SHELL := /bin/bash
.DEFAULT_GOAL := help

# ====== Nastavení ======
VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

RUFF   := $(PYTHON) -m ruff
PYTEST := $(PYTHON) -m pytest

# Verze / cesty
HA_VERSION := 2025.9.4
BAKALARI_VERSION := 0.7.0
HA_CONFIG := ./config
COMPONENT_PATH := custom_components/bakalari

# Hassfest z core repa (bez instalace dev core)
HASSFEST_CORE_DIR := .ha-core
HASSFEST_REPO := https://github.com/home-assistant/core
# ev. $(HA_VERSION)
HASSFEST_REF ?= dev

# Prostředí
export VIRTUAL_ENV_DISABLE_PROMPT=1
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PYTHONDONTWRITEBYTECODE=1

.PHONY: help venv install update \
        lint fmt fix test coverage ci \
        hassfest-setup hassfest-local hacs-local validate-local validate-all \
        run run-debug run-no-cache \
        clean distclean bump-ha bump-bakalari check-versions

help:
	@echo "Použití:"
	@echo "  make venv                            - vytvoří .venv"
	@echo "  make install                         - nainstaluje závislosti (stable HA $(HA_VERSION))"
	@echo "  make update                          - smaže .venv a nainstaluje znovu"
	@echo "  make bump-ha NEW=<version>           - zvýší verzi HA"
	@echo "  make bump-bakalari NEW=<version>     - zvýší verzi bakaláře"
	@echo "  make bump-version NEW=<version>      - zvýší verzi balíčku"
	@echo "  make all                             - spustí všecny potřebné testy"
	@echo "  make lint                            - ruff check + format check"
	@echo "  make fmt                             - ruff format"
	@echo "  make fix                             - ruff check --fix"
	@echo "  make test                            - pytest (tiché -q)"
	@echo "  make coverage                        - pytest s coverage"
	@echo "  make ci                              - lint + test"
	@echo "  make run                             - spustí HA z .venv (config: $(HA_CONFIG))"
	@echo "  make run-debug                       - spustí HA s --debug"
	@echo "  make run-no-cache                    - spustí HA s --skip-pip (rychlé iterace)"
	@echo "  make hassfest-local                  - spustí hassfest na $(COMPONENT_PATH)"
	@echo "  make hacs-local                      - HACS validace na $(COMPONENT_PATH)"
	@echo "  make validate-local                  - hassfest + HACS"
	@echo "  make check-versions                - zkontroluje správnost verzí"
	@echo "  make clean                           - smaže cache (pytest/ruff/build)"
	@echo "  make distclean                       - clean + smaže .venv a .ha-core"

# ====== Venv & instalace ======
venv:
	python3 -m venv $(VENV)
	@echo "✅ Venv vytvořen v $(VENV)"

install: venv
	$(PYTHON) -m pip install --upgrade pip wheel
	# Pinované jádro Home Assistantu
	$(PYTHON) -m pip install "homeassistant==$(HA_VERSION)"
	$(PYTHON) -m pip install -e .
	$(PYTHON) -m pip install \
		ruff pre-commit \
		pytest pytest-asyncio pytest-homeassistant-custom-component \
		async-bakalari-api==$(BAKALARI_VERSION) \
		bump-my-version PyTurboJPEG \
		basedpyright
	$(MAKE) hassfest-setup

update:
	@echo "🧹 Aktualizace prostředí..."
	rm -rf $(VENV)
	$(MAKE) install
	@echo "✅ Hotovo."

all: ci coverage validate-local check-versions

# ====== Lint & test ======
lint:
	@echo -n "Ruff check : "
	@$(RUFF) check .
	@echo -n "Ruff format: "
	@$(RUFF) format --check .
	@set -o pipefail; \
		basedpyright --outputjson | python script/pretty_basedpyright.py

fmt:
	@$(RUFF) format .

fix:
	@$(RUFF) check --fix .

test:
	@$(PYTEST) -q

coverage:
	@$(PYTEST) --cov=custom_components.bakalari --cov-report=term-missing

ci: lint test

# ====== Hassfest (bez dev core instalace) ======
hassfest-setup:
	@if ! command -v git >/dev/null 2>&1; then \
	  echo "❌ git není dostupný v PATH"; exit 1; \
	fi
	@if [ ! -d "$(HASSFEST_CORE_DIR)/.git" ]; then \
	  echo "📥 Cloning Home Assistant core ($(HASSFEST_REF))..."; \
	  git clone --depth 1 --branch $(HASSFEST_REF) $(HASSFEST_REPO) $(HASSFEST_CORE_DIR); \
	else \
	  echo "🔄 Updating Home Assistant core ($(HASSFEST_REF))..."; \
	  git -C $(HASSFEST_CORE_DIR) fetch --depth 1 origin $(HASSFEST_REF); \
	  git -C $(HASSFEST_CORE_DIR) checkout -q $(HASSFEST_REF) || true; \
	  git -C $(HASSFEST_CORE_DIR) reset --hard -q origin/$(HASSFEST_REF) || true; \
	fi

hassfest-local: hassfest-setup
	PYTHONPATH=$(HASSFEST_CORE_DIR) $(PYTHON) -m script.hassfest --integration-path $(COMPONENT_PATH)

# ====== HACS validace ======
hacs-local:
	@if ! command -v docker >/dev/null 2>&1; then \
	  echo "❌ Docker není k dispozici."; exit 1; \
	fi
	@if [ -z "$$GITHUB_TOKEN" ]; then \
	  echo "❌ Chybí GITHUB_TOKEN (export GITHUB_TOKEN=... )"; exit 1; \
	fi
	docker run --rm \
	  --platform linux/amd64 \
	  -e GITHUB_TOKEN=$$GITHUB_TOKEN \
	  -e INPUT_CATEGORY=integration \
	  -e INPUT_IGNORE=brands \
	  -v "$$(pwd)":/github/workspace \
	  ghcr.io/hacs/action:main

validate-local: hassfest-local
validate-all: ci validate-local

# ====== Spouštění Home Assistanta z venvu ======
run:
	@$(PYTHON) -m homeassistant --config $(HA_CONFIG)

run-debug:
	@$(PYTHON) -m homeassistant --config $(HA_CONFIG) --debug

run-no-cache:
	@$(PYTHON) -m homeassistant --config $(HA_CONFIG) --skip-pip

# ====== Úklid ======
clean:
	@rm -rf .pytest_cache .ruff_cache build dist *.egg-info
	@echo "🧹 Cache uklizena."

distclean: clean
	@rm -rf $(VENV) $(HASSFEST_CORE_DIR)
	@echo "🧨 .venv i .ha-core smazány."

# ======= Bump verze ======

bump-ha:
	@if [ -z "$(NEW)" ]; then echo "Použití: make bump-ha NEW=<verze>"; exit 1; fi
	@bump-my-version bump --allow-dirty --no-commit --config-file ./bump-ha.toml --current-version "$$(tomlq -f ./bump-ha.toml '.tool.bumpversion.current_version' 2>/dev/null || sed -n "s/^current_version = \"\(.*\)\"/\1/p" ./bump-ha.toml | head -1)" --new-version "$(NEW)"

bump-bakalari:
	@if [ -z "$(NEW)" ]; then echo "Použití: make bump-bakalari NEW=<verze>"; exit 1; fi
	@bump-my-version bump --allow-dirty --no-commit --config-file ./bump-bakalari.toml --current-version "$$(tomlq -f ./bump-bakalari.toml '.tool.bumpversion.current_version' 2>/dev/null || sed -n "s/^current_version = \"\(.*\)\"/\1/p" ./bump-bakalari.toml | head -1)" --new-version "$(NEW)"
bump-version:
	@if [ -z "$(NEW)" ]; then echo "Použití: make bump-version NEW=<verze>"; exit 1; fi
	@bump-my-version bump --allow-dirty --no-commit --config-file ./bump-version.toml --current-version "$$(tomlq -f ./bump-version.toml '.tool.bumpversion.current_version' 2>/dev/null || sed -n "s/^current_version = \"\(.*\)\"/\1/p" ./bump-version.toml | head -1)" --new-version "$(NEW)"

check-versions:
	@echo "🔍 Kontrola konzistence verzí..."
	@$(PYTHON) script/validate_version.py
