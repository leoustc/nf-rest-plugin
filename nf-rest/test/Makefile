NXF_ARGS ?=

all: prod

prod: clean
	nextflow run main.nf -c rest.config

clean:
	rm -f .nextflow.log*
