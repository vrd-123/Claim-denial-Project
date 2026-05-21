from fastapi import APIRouter, UploadFile, File, HTTPException
from api.services.ocr_service import parse_document
from api.services.validation_service import validate_extracted
import os

router = APIRouter()

@router.post("/extract-claim")
async def extract_claim(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(400, "No file provided")
    
    try:
        raw_text = await parse_document(file)
        from api.services.llm_service import extract_fields_with_llm
        extracted = await extract_fields_with_llm(raw_text)
        validation = validate_extracted(extracted)
        
        return {
            "status": "success",
            "extracted": extracted,
            "validation": validation,
            "raw_text": raw_text[:500] + "..." if len(raw_text) > 500 else raw_text
        }
    except Exception as e:
        raise HTTPException(500, str(e))
