# Build the plugin
.PHONY: all assemble install clean

all:	clean assemble install

assemble:
	./gradlew assemble

# Install the plugin into local nextflow plugins dir
install:
	./gradlew install

clean:
	rm -rf .nextflow*
	rm -rf work
	rm -rf build
	./gradlew clean
