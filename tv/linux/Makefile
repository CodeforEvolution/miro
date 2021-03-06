SHELL = /bin/sh

prefix = /usr
distdir = dist
exec_prefix = $(prefix)
bindir = $(distdir)$(exec_prefix)/bin
python = $(shell which python)
python_version = $(shell $(python) -c 'import sys; info=sys.version_info; print "%s.%s" % (info[0], info[1])')

SITE32PATH = $(shell pwd)/dist$(prefix)/lib/python$(python_version)/site-packages/
SITE64PATH = $(shell pwd)/dist$(prefix)/lib64/python$(python_version)/site-packages/
MIROPYTHONPATH = $(SITE32PATH):$(SITE64PATH)

.PHONY: build run test pylint

build:
	$(python) setup.py install --root=./dist --prefix=$(prefix)

run: build
	MIRO_SHARE_ROOT=dist/$(prefix)/share/ \
	   MIRO_RESOURCE_ROOT=dist/$(prefix)/share/miro/resources/ \
	   PATH=dist$(prefix)/bin \
	   PYTHONPATH=$(MIROPYTHONPATH) \
	   $(bindir)/miro

test: build
	MIRO_SHARE_ROOT=dist/$(prefix)/share/ \
	   MIRO_RESOURCE_ROOT=dist/$(prefix)/share/miro/resources/ \
	   PATH=dist$(prefix)/bin \
	   PYTHONPATH=$(MIROPYTHONPATH) \
	   $(bindir)/miro --unittest

pylint: build
	# remove .so files that pylint flips out on
	find dist -name "*.so" | xargs rm
	rm -rf dist/usr/lib/python2.6/site-packages/miro/test
	cd dist/$(prefix)/lib/python$(python_version)/site-packages && \
	   pylint --rcfile ../../../../../pylintrc miro > ../../../../../pylint.output 2>&1
