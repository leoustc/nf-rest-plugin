NXF_ARGS ?=

all: dev

prod: clean
	nextflow run main.nf -c rest.config

dev:	clean
	NXF_DEBUG=3 nextflow run dev.nf -c rest.config

clean:
	rm -f .nextflow.log*
