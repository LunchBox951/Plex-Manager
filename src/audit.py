"""
Audit logging utilities for tracking user actions.
Provides accountability and debugging information during development.
"""

import json
from datetime import datetime
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any
from fastapi import Request

from src.models import AuditLog


def log_action(
    db: Session,
    user_id: int,
    action_type: str,
    entity_type: str,
    entity_id: Optional[int] = None,
    old_value: Optional[Dict[str, Any]] = None,
    new_value: Optional[Dict[str, Any]] = None,
    description: Optional[str] = None,
    request: Optional[Request] = None
) -> AuditLog:
    """
    Log a user action to the audit trail and print to terminal for development.
    
    Args:
        db: Database session
        user_id: ID of user performing action
        action_type: Type of action (e.g., 'retention_change', 'request_created')
        entity_type: Type of entity affected (e.g., 'media_request', 'episode')
        entity_id: ID of affected entity
        old_value: Dictionary of old state (will be JSON serialized)
        new_value: Dictionary of new state (will be JSON serialized)
        description: Human-readable description
        request: FastAPI request object for extracting IP/user agent
    
    Returns:
        Created AuditLog entry
    """
    # Create audit log entry
    audit_entry = AuditLog(
        user_id=user_id,
        action_type=action_type,
        entity_type=entity_type,
        entity_id=entity_id,
        old_value=json.dumps(old_value) if old_value else None,
        new_value=json.dumps(new_value) if new_value else None,
        description=description,
        ip_address=request.client.host if request and hasattr(request, 'client') and request.client else None,
        user_agent=request.headers.get('user-agent') if request and hasattr(request, 'headers') else None,
        created_at=datetime.utcnow()
    )
    
    db.add(audit_entry)
    db.commit()
    
    # Print to terminal for development monitoring
    timestamp = audit_entry.created_at.strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*80}")
    print(f"AUDIT LOG [{timestamp}]")
    print(f"{'='*80}")
    print(f"User ID:     {user_id}")
    print(f"Action:      {action_type}")
    print(f"Entity:      {entity_type} (ID: {entity_id})")
    
    if description:
        print(f"Description: {description}")
    
    if old_value:
        print(f"\nOld Value:")
        for key, val in old_value.items():
            print(f"  {key}: {val}")
    
    if new_value:
        print(f"\nNew Value:")
        for key, val in new_value.items():
            print(f"  {key}: {val}")
    
    if request:
        print(f"\nContext:")
        print(f"  IP Address:  {audit_entry.ip_address}")
        print(f"  User Agent:  {audit_entry.user_agent}")
    
    print(f"{'='*80}\n")
    
    return audit_entry
