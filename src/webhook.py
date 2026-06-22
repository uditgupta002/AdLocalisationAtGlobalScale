import asyncio
from fastapi import FastAPI, Request, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import List, Optional
from src.config import settings
from src.utils.logger import setup_logger
from src.utils.idempotency import IdempotencyStore

logger = setup_logger("swarm-webhook")
idempotency = IdempotencyStore()

app = FastAPI(title="Canva Content Swarm Webhook Server", version="1.0.0")
security = HTTPBearer()

# Pydantic schemas for Tigris Event Payload validation
class TigrisObject(BaseModel):
    key: str
    size: int
    eTag: Optional[str] = None

class TigrisEvent(BaseModel):
    eventName: str
    eventTime: str
    bucket: str
    object: TigrisObject

class TigrisWebhookPayload(BaseModel):
    events: List[TigrisEvent]


def authenticate_webhook(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Validate authorization bearer token.
    """
    token = credentials.credentials
    if token != settings.WEBHOOK_AUTH_TOKEN:
        logger.warning("Unauthorized webhook access attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature or unauthorized bearer token"
        )


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.post("/webhook/tigris")
async def handle_tigris_webhook(
    payload: TigrisWebhookPayload,
    authenticated: None = Depends(authenticate_webhook)
):
    """
    FastAPI endpoint for Tigris S3 Object Notifications.
    Acknowledges the webhook immediately to Tigris (within 10s window) 
    and handles downstream orchestration asynchronously in a background task.
    """
    logger.info(f"Received webhook containing {len(payload.events)} event(s)")
    
    # Import router locally to prevent circular imports during start
    from src.router import route_object_event
    
    events_to_process = []
    
    for event in payload.events:
        # Prevent double execution (idempotency check)
        event_id = f"{event.bucket}:{event.object.key}:{event.object.eTag or 'none'}"
        if idempotency.is_duplicate(event_id):
            logger.warning(f"Duplicate event filtered: {event_id}")
            continue
        
        idempotency.record(event_id)
        events_to_process.append(event)
        
    # Process valid events in background to keep endpoint responsive
    for event in events_to_process:
        asyncio.create_task(process_event_async(event))
        
    return {"received": True, "processed_count": len(events_to_process)}


async def process_event_async(event: TigrisEvent):
    from src.router import route_object_event
    try:
        logger.info(f"Background task starting for event: {event.object.key}")
        await route_object_event(event)
    except Exception as e:
        logger.error(f"Error executing event routing background task for {event.object.key}: {e}", exc_info=True)
