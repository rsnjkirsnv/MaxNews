from pydantic import BaseModel

class AliceRequest(BaseModel):
    request: dict
    session: dict
    version: str


class AliceResponse(BaseModel):
    response: dict
    session: dict
    version: str


class HealthCheck(BaseModel):
    status: str
    timestamp: str
    service_uptime: str
    service: str
    version: str
    max_service: str