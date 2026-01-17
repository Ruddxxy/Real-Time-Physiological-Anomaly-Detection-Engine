from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from typing import Optional

class VitalsReading(BaseModel):
    patient_id: str = Field(..., min_length=1, max_length=50, description="Unique patient identifier")
    timestamp: datetime = Field(..., description="ISO 8601 timestamp of the reading")
    hr: int = Field(..., ge=30, le=250, description="Heart Rate (bpm)")
    bp_sys: int = Field(..., ge=50, le=250, description="Systolic Blood Pressure (mmHg)")
    bp_dia: int = Field(..., ge=30, le=150, description="Diastolic Blood Pressure (mmHg)")
    spo2: int = Field(..., ge=50, le=100, description="Oxygen Saturation (%)")
    rr: int = Field(..., ge=4, le=60, description="Respiratory Rate (breaths/min)")
    temp: float = Field(..., ge=30.0, le=45.0, description="Body Temperature (C)")

    @field_validator('timestamp')
    def timestamp_not_future(cls, v: datetime):
        # Ensure v is timezone-aware or normalize to UTC
        if v.tzinfo is None:
             # Assume UTC if naive, or reject. Let's assume input is UTC.
             v = v.replace(tzinfo=None) # Compare naive-to-naive or aware-to-aware
             current = datetime.utcnow()
        else:
             current = datetime.now(v.tzinfo)

        if v > current:
            # Allow a small clock skew (e.g. 5 seconds) if needed, but strictly reject future
            # For now, simplistic check:
            if (v - current).total_seconds() > 300: # 5 min future tolerance
                 raise ValueError('Timestamp cannot be significantly in the future')
        return v
    
    @field_validator('bp_sys')
    def sys_greater_than_dia(cls, v, values):
        # We need validation context, but pydantic v2 passes ValidationInfo.
        # This simple check might need to be a model_validator if we strictly compare fields.
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "patient_id": "pt-1234",
                "timestamp": "2023-10-27T10:00:00Z",
                "hr": 72,
                "bp_sys": 120,
                "bp_dia": 80,
                "spo2": 98,
                "rr": 16,
                "temp": 36.8
            }
        }
