# Define variables
IMAGE_NAME = nasfong/machine-learning
TAG = latest
DOCKERFILE_PATH = .
DOCKERFILE_PROD = Dockerfile

# Build the Docker image
build:
	docker build -f $(DOCKERFILE_PROD) -t $(IMAGE_NAME):$(TAG) $(DOCKERFILE_PATH)

# Run the Docker container locally
run:
	docker run -p 8000:8000 --rm --name ml-api $(IMAGE_NAME):$(TAG)

# Run in detached mode
run-detached:
	docker run -d -p 8000:8000 --name ml-api $(IMAGE_NAME):$(TAG)

# Stop the running container
stop:
	docker stop ml-api

# Push the Docker image to Docker Hub
push:
	docker push $(IMAGE_NAME):$(TAG)

# Pull the Docker image from Docker Hub
pull:
	docker pull $(IMAGE_NAME):$(TAG)

# Build and push the Docker image in one step
build-and-push: build push

# Pull and run the Docker image
pull-and-run: pull
	docker run -p 8000:8000 --rm $(IMAGE_NAME):$(TAG)

# Build and run locally
build-and-run: build run

# View logs
logs:
	docker logs -f ml-api

# Execute shell in running container
shell:
	docker exec -it ml-api /bin/bash

# Clean up unused Docker images and containers
clean:
	docker system prune -f

# Remove specific image
remove-image:
	docker rmi $(IMAGE_NAME):$(TAG)

# Full cleanup (stop container and remove image)
full-clean: stop remove-image clean

dev:
	uvicorn main:app --reload

# Help command
help:
	@echo "Available commands:"
	@echo "  make build          - Build Docker image"
	@echo "  make run            - Run container locally"
	@echo "  make run-detached   - Run container in background"
	@echo "  make stop           - Stop running container"
	@echo "  make push           - Push image to Docker Hub"
	@echo "  make pull           - Pull image from Docker Hub"
	@echo "  make build-and-push - Build and push image"
	@echo "  make pull-and-run   - Pull and run image"
	@echo "  make build-and-run  - Build and run locally"
	@echo "  make logs           - View container logs"
	@echo "  make shell          - Open shell in container"
	@echo "  make clean          - Clean up Docker system"
	@echo "  make remove-image   - Remove specific image"
	@echo "  make full-clean     - Stop container and cleanup"