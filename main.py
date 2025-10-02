from fastapi import FastAPI
from pydantic import BaseModel
import numpy as np
from typing import List

app = FastAPI(title="ML API", version="1.0")

# Simple mock ML model (linear prediction)
class MLModel:
    def __init__(self):
        self.weights = np.array([0.5, 0.3, 0.2])
        self.bias = 0.1
    
    def predict(self, features: List[float]) -> float:
        return float(np.dot(features, self.weights) + self.bias)

model = MLModel()

class PredictionRequest(BaseModel):
    features: List[float]

class PredictionResponse(BaseModel):
    prediction: float

@app.get("/")
def root():
    return {"message": "ML API is running"}

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.post("/predict", response_model=PredictionResponse)
def predict(request: PredictionRequest):
    if len(request.features) != 3:
        return {"error": "Expected 3 features"}
    
    prediction = model.predict(request.features)
    return {"prediction": prediction}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)