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

import string
import time

@app.post("/api/v1/macro/execute", response_model=MacroResponse)
async def execute_macro(request: MacroRequest, token: str = Depends(verify_token)):
    """
    FIXED: CWE-94 Code Injection mitigated by removing exec().
    Replaced arbitrary Python code execution with safe string templating and predefined operations.
    """
    start_time = time.time()
    
    if request.document_id not in DOCUMENT_STORE:
        SERVICE_METRICS["errors"] += 1
        raise HTTPException(status_code=404, detail="Document not found for macro execution")

    doc = DOCUMENT_STORE[request.document_id]
    original_content = doc["content"]
    # We now treat 'macro_code' as a strict keyword for an operation, not executable code
    macro_action = request.macro_code.lower() 
    variables = request.variables or {}
    
    logger.info(f"Executing safe macro '{request.macro_name}' on document '{request.document_id}'")
    SERVICE_METRICS["macro_executions"] += 1

    try:
        # FIXED SINK: exec() is removed.
        # Step 1: Use Python's built-in safe string substitution for variables
        # This replaces occurrences of $var or ${var} in the text safely.
        template = string.Template(original_content)
        transformed = template.safe_substitute(**variables)
        
        # Step 2: Apply a predefined mapping of safe string transformations
        if macro_action == 'uppercase':
            transformed = transformed.upper()
        elif macro_action == 'lowercase':
            transformed = transformed.lower()
        elif macro_action == 'append_user' and 'user' in variables:
            transformed = f"{transformed} [EDITED BY {variables['user']}]"
        elif macro_action not in ['', 'none']:
            raise ValueError(f"Unsupported macro operation: {macro_action}")
        
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
            detail=f"Macro execution error: {str(e)}"
        )

if __name__ == "__main__":
    logger.info("Starting up FastAPI application on port 8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
