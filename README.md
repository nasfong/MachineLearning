# FastAPI ML API

A minimal FastAPI project with Docker for ML predictions.

## Project Structure
```
.
├── main.py              # FastAPI application
├── requirements.txt     # Python dependencies
├── Dockerfile          # Docker configuration
├── Makefile            # Build and deployment commands
└── README.md           # This file
```

## Prerequisites

- Docker installed
- Python 3.11+ (for local development without Docker)
- Docker Hub account (for pushing images)

## Quick Start

### Using Makefile (Recommended)

```bash
# Build and run locally
make build-and-run

# View all available commands
make help
```

### Manual Docker Commands

```bash
# Build image
docker build -t nasfong/machine-learning:latest .

# Run container
docker run -p 8000:8000 --rm nasfong/machine-learning:latest
```

### Without Docker

```bash
# Install dependencies
pip install -r requirements.txt

# Run application
python main.py
```

## Usage

Once running, access:
- **API Documentation**: http://localhost:8000/docs
- **Alternative Docs**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health

### Test the Prediction Endpoint

**Using curl:**
```bash
curl -X POST "http://localhost:8000/predict" \
  -H "Content-Type: application/json" \
  -d '{"features": [1.0, 2.0, 3.0]}'
```

**Using Python:**
```python
import requests

response = requests.post(
    "http://localhost:8000/predict",
    json={"features": [1.0, 2.0, 3.0]}
)
print(response.json())
# Output: {"prediction": 1.2}
```

**Using the interactive docs:**
1. Go to http://localhost:8000/docs
2. Click on `POST /predict`
3. Click "Try it out"
4. Enter your features array
5. Click "Execute"

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Root endpoint - API info |
| GET | `/health` | Health check |
| POST | `/predict` | Make predictions (requires 3 features) |

### Request/Response Examples

**POST /predict**

Request:
```json
{
  "features": [1.0, 2.0, 3.0]
}
```

Response:
```json
{
  "prediction": 1.2
}
```

## Makefile Commands

### Development Commands
```bash
make build              # Build Docker image
make run                # Run container locally
make run-detached       # Run container in background
make stop               # Stop running container
make logs               # View container logs
make shell              # Open bash shell in container
make build-and-run      # Build and run in one step
```

### Deployment Commands
```bash
make push               # Push image to Docker Hub
make pull               # Pull image from Docker Hub
make build-and-push     # Build and push to Docker Hub
make pull-and-run       # Pull and run from Docker Hub
```

### Cleanup Commands
```bash
make clean              # Clean up Docker system
make remove-image       # Remove specific image
make full-clean         # Stop container and full cleanup
```

### Help
```bash
make help               # Show all available commands
```

## Deployment

### Deploy to Docker Hub

1. **Login to Docker Hub:**
```bash
docker login
```

2. **Build and push:**
```bash
make build-and-push
```

### Deploy on Server

1. **Pull and run:**
```bash
make pull-and-run
```

2. **Or run detached:**
```bash
docker pull nasfong/machine-learning:latest
docker run -d -p 8000:8000 --name ml-api nasfong/machine-learning:latest
```

## Customization

### Replace with Your ML Model

Update the `MLModel` class in `main.py`:

```python
# Example with scikit-learn
import joblib

class MLModel:
    def __init__(self):
        self.model = joblib.load('model.pkl')
    
    def predict(self, features):
        return float(self.model.predict([features])[0])
```

### Add More Dependencies

Add to `requirements.txt`:
```txt
scikit-learn==1.3.2
pandas==2.1.3
```

Then rebuild:
```bash
make build
```

## Environment Variables

You can pass environment variables when running:

```bash
docker run -p 8000:8000 \
  -e MODEL_PATH=/app/models \
  -e LOG_LEVEL=debug \
  --rm nasfong/machine-learning:latest
```

## Troubleshooting

### Port already in use
```bash
# Change the port mapping
docker run -p 8080:8000 --rm nasfong/machine-learning:latest
```

### View container logs
```bash
make logs
# or
docker logs -f ml-api
```

### Debug inside container
```bash
make shell
# or
docker exec -it ml-api /bin/bash
```

### Container won't start
```bash
# Check Docker logs
docker ps -a
docker logs <container-id>
```

## Performance Optimization

### Multi-stage Build (Optional)

For production, consider a multi-stage Dockerfile:
```dockerfile
FROM python:3.11-slim as builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --user -r requirements.txt

FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY main.py .
ENV PATH=/root/.local/bin:$PATH
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## Contributing

1. Fork the repository
2. Create your feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

MIT License

## Support

For issues and questions:
- Open an issue on GitHub
- Check the [FastAPI documentation](https://fastapi.tiangolo.com/)
- Check the [Docker documentation](https://docs.docker.com/)