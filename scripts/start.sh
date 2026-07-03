#!/bin/bash

# Start API server in background
uvicorn src.api:app --host 0.0.0.0 --port 8000 &

# Wait for API to be ready
sleep 3

# Start Streamlit frontend
streamlit run frontend/app.py --server.port 8501 --server.address 0.0.0.0
