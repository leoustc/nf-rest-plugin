.PHONY: all clean run logs save update

all: 	clean build-proxy-runtime run logs

fresh: clean build run logs

run:
	docker compose up -d --force-recreate

build: build-gateway build-proxy-base build-proxy-runtime

build-gateway:
	cd src/gateway && docker build -t rest-gateway:latest -t leoustc/nf-server:gateway.v2 -f Dockerfile .

build-proxy-base:
	cd src/proxy && docker build --target base -t rest-proxy-base:latest -f Dockerfile .

build-proxy-runtime:
	cd src/proxy && docker build --target runtime -t rest-proxy:latest -t leoustc/nf-server:proxy.v2 -f Dockerfile .

.PHONY: push-gateway push-proxy push
push:	push-gateway push-proxy

push-gateway: build-gateway
	docker push leoustc/nf-server:gateway.v2

push-proxy: build-proxy-base build-proxy-runtime
	docker push leoustc/nf-server:proxy.v2

logs:
	docker compose logs -f

clean:
	docker compose down --volumes --remove-orphans

reset: clean
	sudo rm -rf tmp
	sudo rm -rf mysql-data
