SHELL := /bin/bash

# ====== Nastavení ======
VENV := .venv
PYTHON := $(VENV)/bin/python
PIP    := $(VENV)/bin/pip
RUFF   := $(VENV)/bin/ruff
PYTEST := $(VENV)/bin/pytest

# Runner image pro act
ACT_IMAGE ?= catthehacker/ubuntu:act-latest
# pro Apple Silicon lze zachovat stejné mapování (act si poradí s emulací),
# případně si přidej: ACT_PLATFORM = -P ubuntu-latest=$(ACT_IMAGE)

# Verze pro testovací prostředí (držet v sync s CI)
HA_VERSION := 2025.1.4
BAKALARI_VERSION := 0.3.6

.PHONY: help venv install lint test ci clean \
        act-tests act-validate act-all act-setup

help:
	@echo "Použití:"
	@echo "  make venv         - vytvoří $(VENV)"
	@echo "  make install      - nainstaluje dev závislosti (ruff, pytest..., HA, async-bakalari-api)"
	@echo "  make lint         - ruff check + format check"
	@echo "  make test         - pytest (z $(VENV))"
	@echo "  make ci           - == lint + test (lokální replika CI)"
	@echo "  make act-setup    - nainstaluje 'act' (GitHub Actions lokálně)"
	@echo "  make act-tests    - spustí job 'tests' z CI workflow"
	@echo "  make act-validate - spustí 'hassfest' a 'hacs' z validate workflow"
	@echo "  make act-all      - tests + validate přes act"
	@echo "  make clean        - smaže $(VENV) a cache"

venv:
	python3 -m venv $(VENV)

install: venv
	$(PIP) install --upgrade pip
	$(PIP) install -e .
	$(PIP) install \
		ruff pre-commit \
		pytest pytest-asyncio pytest-homeassistant-custom-component \
		homeassistant==$(HA_VERSION) \
		async-bakalari-api==$(BAKALARI_VERSION)
	# volitelné pluginy do pytestu:
	# $(PIP) install pytest-sugar pytest-cov respx anyio requests-mock

lint:
	$(RUFF) check .
	$(RUFF) format --check .

test:
	$(PYTHON) -m pytest -q

ci: lint test

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache build dist

# ====== GitHub Actions lokálně (act) ======

act-tests:
	@if ! command -v act >/dev/null 2>&1; then echo "❌ act není nainstalováno. Spusť: make act-setup"; exit 1; fi
	act push -j tests -P ubuntu-latest=$(ACT_IMAGE)

act-validate:
	@if ! command -v act >/dev/null 2>&1; then echo "❌ act není nainstalováno. Spusť: make act-setup"; exit 1; fi
	act push -j hassfest -P ubuntu-latest=$(ACT_IMAGE)
	act push -j hacs     -P ubuntu-latest=$(ACT_IMAGE)

act-all: act-tests act-validate

# Bez .ONESHELL: vše v jednom shellu přes zpětná lomítka
act-setup:
	@if command -v act >/dev/null 2>&1; then \
		echo "✅ act už je nainstalované: $$(command -v act)"; \
		exit 0; \
	fi; \
	if command -v brew >/dev/null 2>&1; then \
		echo "🍺 Instalace přes Homebrew…"; \
		brew install act || true; \
	else \
		echo "⬇️  Stahuji binárku act…"; \
		ACT_VERSION=$$(curl -fsSL https://api.github.com/repos/nektos/act/releases/latest | grep -m1 '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/'); \
		OSN=$$(uname -s); \
		ARCHN=$$(uname -m); \
		URL="https://github.com/nektos/act/releases/download/$${ACT_VERSION}/act_$${OSN}_$${ARCHN}.tar.gz"; \
		echo "URL: $$URL"; \
		TMP=$$(mktemp -d); \
		curl -fsSL -o "$$TMP/act.tgz" "$$URL"; \
		mkdir -p "$$HOME/.local/bin"; \
		tar -xzf "$$TMP/act.tgz" -C "$$HOME/.local/bin" act || { echo "❌ Rozbalení selhalo (možná jiný název assetu pro tvou architekturu)."; exit 1; }; \
		rm -rf "$$TMP"; \
		echo "✅ act nainstalováno do $$HOME/.local/bin/act"; \
		echo '👉 Přidej do PATH (pokud tam ještě není): export PATH="$$HOME/.local/bin:$$$${PATH}"'; \
	fi
