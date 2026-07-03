"""
FastAPI backend for Smart BI Agent
"""
import os
import sys
import json
from typing import Optional
from contextlib import asynccontextmanager

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.core.schema_manager import SchemaManager
from src.core.fewshot_sql import FewShotSQLLibrary
from src.core.react_agent import ReActAgent
from src.models.llm_client import LLMClient
from config.settings import CONFIG

agent: Optional[ReActAgent] = None
schema_manager: Optional[SchemaManager] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent, schema_manager

    schema_manager = SchemaManager(CONFIG.database.db_path)
    fewshot_lib = FewShotSQLLibrary(CONFIG.database.db_path)

    llm = LLMClient(
        api_key=CONFIG.llm.api_key,
        base_url=CONFIG.llm.base_url,
        model=CONFIG.llm.model,
        temperature=CONFIG.llm.temperature,
        max_tokens=CONFIG.llm.max_tokens,
        use_local=CONFIG.llm.use_local
    )

    agent = ReActAgent(llm, schema_manager, fewshot_lib, CONFIG.database.db_path)

    print("=" * 50)
    print("Smart BI Agent initialized successfully!")
    print(f"Database: {CONFIG.database.db_path}")
    print(f"LLM Model: {CONFIG.llm.model}")
    print("=" * 50)

    yield
    print("Shutting down...")

app = FastAPI(
    title="Smart BI Agent API",
    description="Natural language to SQL analytics API",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class QueryRequest(BaseModel):
    question: str
    enable_viz: bool = True

class QueryResponse(BaseModel):
    success: bool
    answer: str
    sql: str
    data: list
    columns: list
    visualization: Optional[dict]
    execution_time_ms: float

class SchemaResponse(BaseModel):
    tables: list
    schema_text: str

@app.get("/")
async def root():
    return {"message": "Smart BI Agent API", "version": "1.0.0"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "agent_ready": agent is not None}

@app.get("/schema", response_model=SchemaResponse)
async def get_schema():
    if not schema_manager:
        raise HTTPException(status_code=503, detail="Schema manager not initialized")
    return {
        "tables": list(schema_manager.schema_cache.keys()),
        "schema_text": schema_manager.get_full_schema()
    }

@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest):
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    import time
    start = time.time()

    try:
        result = agent.run(request.question)
        execution_time = (time.time() - start) * 1000

        return {
            "success": result["success"],
            "answer": result["final_answer"],
            "sql": result["sql"],
            "data": result["data"],
            "columns": result["columns"],
            "visualization": result["visualization"] if request.enable_viz else None,
            "execution_time_ms": round(execution_time, 2)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/feedback")
async def feedback(query_id: str, correct_sql: str, rating: int):
    return {"status": "received", "query_id": query_id}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=CONFIG.host, port=CONFIG.port)
