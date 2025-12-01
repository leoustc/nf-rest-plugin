# Build the plugin
.PHONY: all assemble install uninstall clean

NEXTFLOW_HOME ?= $(HOME)/.nextflow
PLUGINS_DIR := $(NEXTFLOW_HOME)/plugins
PLUGIN_ID := nf-rest

all:	uninstall clean assemble install

assemble:
	./gradlew assemble --warning-mode all

# Install the plugin into local nextflow plugins dir
install:
	./gradlew install

uninstall:
	rm -rf "$(PLUGINS_DIR)/$(PLUGIN_ID)"*

clean:
	rm -rf .nextflow*
	rm -rf work
	rm -rf build
	./gradlew clean assemble
