PY := invoke

.PHONY: all clean preview build-assets check-tools FORCE

all:
	$(PY) build

clean:
	$(PY) clean

preview:
	$(PY) preview

build-assets:
	$(PY) build-assets

check-tools:
	$(PY) doctor

# Einzelne Datei: make unterricht/informatik/klasse-11/klausuren/klausur-e2-25-26/klausur-e2.qmd
%.qmd: FORCE
	$(PY) build --source $@

FORCE:
