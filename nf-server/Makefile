.PHONY: all clean run logs build-base build-runtime save update

all: clean build-runtime run logs

fresh: clean build-base build-runtime run logs

build-base:
	docker build --target base -t rest-executor-base:latest src

build-runtime:
	docker build --target runtime -t rest-executor:latest src

run:
	docker compose up -d --force-recreate

connect:
	docker exec -it nf-server-rest-executor-0-1 bash

logs:
	docker compose logs -f

clean:
	docker compose down --volumes --remove-orphans
	sudo rm -rf tmp
	sudo rm -rf mysql-data

save:
	git add .
	git commit --amend --no-edit && git push --force-with-lease