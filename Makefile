PYTHON ?= python3
PYTHONPATH := src
PART ?= patch

.PHONY: run gui test typecheck check bump release appimage clean

run:
	./bin/repopull

gui:
	./bin/repopull-gui

test:
	QT_QPA_PLATFORM=offscreen PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m unittest discover -s tests -v

typecheck:
	@if mypy --version >/dev/null 2>&1; then \
		mypy --config-file pyproject.toml; \
	else \
		echo "mypy not installed; using uvx"; \
		uvx mypy --config-file pyproject.toml; \
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

check: typecheck test

clean:
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	rm -rf .mypy_cache
