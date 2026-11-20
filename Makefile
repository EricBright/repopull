PYTHON ?= python3
PYTHONPATH := src
PART ?= patch

.PHONY: run gui dev-env check-env test typecheck check audit soak soak-qt bump release appimage clean

run:
	./bin/repopull

gui:
	./bin/repopull-gui

test:
	QT_QPA_PLATFORM=offscreen PYTHONPATH=$(PYTHONPATH) $(PYTHON) -X dev -X faulthandler -W error -m unittest discover -s tests -v

dev-env:
	$(PYTHON) -m venv .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/python -m pip install -e '.[gui]' \
		-c packaging/runtime-requirements.txt \
		-r packaging/ci-requirements.txt
	@echo "Ready: make check PYTHON=.venv/bin/python"

check-env:
	@$(PYTHON) -c "import PySide6" 2>/dev/null || { \
		echo "PySide6 is missing for $(PYTHON)."; \
		echo "The GUI tests would be skipped, so this gate would pass blind."; \
		echo "Run 'make dev-env', then 'make check PYTHON=.venv/bin/python'."; \
		exit 1; \
	}

typecheck:
	@if $(PYTHON) -m mypy --version >/dev/null 2>&1; then \
		$(PYTHON) -m mypy --config-file pyproject.toml; \
	else \
		echo "mypy not installed for $(PYTHON); using uvx"; \
		uvx mypy --config-file pyproject.toml; \
	fi

audit:
	@if $(PYTHON) -m pip_audit --version >/dev/null 2>&1; then \
		$(PYTHON) -m pip_audit -r packaging/runtime-requirements.txt; \
		$(PYTHON) -m pip_audit -r packaging/build-requirements.txt; \
	else \
		echo "pip-audit not installed for $(PYTHON); using uvx"; \
		uvx pip-audit -r packaging/runtime-requirements.txt; \
		uvx pip-audit -r packaging/build-requirements.txt; \
	fi

bump:
	$(PYTHON) packaging/bump_version.py $(PART)

release: check
	$(PYTHON) packaging/bump_version.py $(PART)
	@echo "Add a CHANGELOG.md entry for the new version."
	$(MAKE) appimage

appimage:
	@test -d build/packaging-env || $(PYTHON) -m venv build/packaging-env
	build/packaging-env/bin/python -m pip install -r packaging/build-requirements.txt
	build/packaging-env/bin/python packaging/build_appimage.py

check: check-env typecheck test

soak:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) tools/soak.py

soak-qt:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) tools/soak.py --qt

clean:
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	rm -rf .mypy_cache
