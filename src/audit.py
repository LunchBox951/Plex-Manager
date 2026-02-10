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
from src.console import print_audit


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
    
    # Print to terminal using console.py unified logging
    details = {
        "User ID": user_id,
        "Action": action_type,
        "Entity": f"{entity_type} (ID: {entity_id})"
    }
    
    if description:
        details["Description"] = description
    
    if old_value:
        for key, val in old_value.items():
            details[f"Old {key}"] = val
    
    if new_value:
        for key, val in new_value.items():
            details[f"New {key}"] = val
    
    if request:
        details["IP Address"] = audit_entry.ip_address
        details["User Agent"] = audit_entry.user_agent
    
    print_audit(
        action=f"{action_type} - {entity_type}",
        details=details
    )
    
    return audit_entry
