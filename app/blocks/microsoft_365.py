"""
Microsoft 365 Integration Module
Handles Teams, Outlook, SharePoint, and OneDrive integration.
"""
import os
import requests

# Ported (real) from Cerebrum backend/app/integrations/microsoft_365.py.
# The SQLAlchemy Microsoft365Connection is not ported: connections are held
# in-process as pydantic records with the same field names. The service's
# Graph request-building, token refresh, and typed request/response models
# are carried verbatim. Unconfigured calls fail closed (structured refusal)
# before any network request.
from datetime import datetime
from typing import List, Optional, Dict, Any
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

from app.core.universal_base import UniversalBlock


MICROSOFT_GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


class Microsoft365Connection(BaseModel):
    """Microsoft 365 connection record (in-process pydantic record).

    Field names and semantics match the donor's SQLAlchemy model; the
    database session is replaced by an in-process store (see the block
    facade below). A missing/invalid credential degrades to a structured
    refusal, never to fabricated Graph data.
    """
    id: str
    tenant_id: Optional[str] = None
    project_id: Optional[str] = None
    organization_id: str = ""
    organization_name: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_expires_at: Optional[datetime] = None
    scopes: List[str] = Field(default_factory=list)
    is_active: bool = True
    connected_by: Optional[str] = None
    connected_at: Optional[datetime] = None
    last_sync_at: Optional[datetime] = None
    settings: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# Pydantic Models

class TeamsMeetingRequest(BaseModel):
    title: str
    start_time: datetime
    end_time: datetime
    description: Optional[str] = None
    attendees: List[str] = []  # Email addresses


class TeamsMeetingResponse(BaseModel):
    id: str
    join_url: str
    start_time: datetime
    end_time: datetime


class SharePointFolderRequest(BaseModel):
    folder_name: str
    parent_folder_id: Optional[str] = None


class OutlookEventRequest(BaseModel):
    subject: str
    start_time: datetime
    end_time: datetime
    attendees: List[str] = []
    location: Optional[str] = None
    body: Optional[str] = None


class Microsoft365Service:
    """Service for Microsoft 365 integration."""
    
    SCOPES = [
        "https://graph.microsoft.com/Calendars.ReadWrite",
        "https://graph.microsoft.com/Chat.ReadWrite",
        "https://graph.microsoft.com/Files.ReadWrite",
        "https://graph.microsoft.com/Group.ReadWrite.All",
        "https://graph.microsoft.com/Mail.ReadWrite",
        "https://graph.microsoft.com/OnlineMeetings.ReadWrite",
        "https://graph.microsoft.com/Sites.ReadWrite.All",
        "https://graph.microsoft.com/TeamMember.ReadWrite.All",
        "https://graph.microsoft.com/TeamsActivity.Send",
        "https://graph.microsoft.com/User.Read"
    ]
    
    def __init__(self, db_session, client_id: str, client_secret: str):
        self.db = db_session
        self.client_id = client_id
        self.client_secret = client_secret
    
    def _get_headers(self, access_token: str) -> Dict[str, str]:
        """Get authorization headers."""
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
    
    def _refresh_token(self, connection: Microsoft365Connection) -> str:
        """Refresh access token."""
        url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
        
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": connection.refresh_token,
            "grant_type": "refresh_token"
        }
        
        response = requests.post(url, data=data)
        response.raise_for_status()
        
        token_data = response.json()
        
        connection.access_token = token_data["access_token"]
        connection.token_expires_at = datetime.utcnow().timestamp() + token_data["expires_in"]
        
        if "refresh_token" in token_data:
            connection.refresh_token = token_data["refresh_token"]
        
        self.db.commit()
        
        return connection.access_token
    
    def _make_request(
        self,
        connection: Microsoft365Connection,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Make authenticated request to Microsoft Graph API."""
        # Check token expiration
        if datetime.utcnow() >= connection.token_expires_at:
            access_token = self._refresh_token(connection)
        else:
            access_token = connection.access_token
        
        url = f"{MICROSOFT_GRAPH_BASE_URL}{endpoint}"
        headers = self._get_headers(access_token)
        
        if method == "GET":
            response = requests.get(url, headers=headers)
        elif method == "POST":
            response = requests.post(url, headers=headers, json=data)
        elif method == "PATCH":
            response = requests.patch(url, headers=headers, json=data)
        elif method == "DELETE":
            response = requests.delete(url, headers=headers)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")
        
        response.raise_for_status()
        return response.json() if response.content else {}
    
    def create_teams_meeting(
        self,
        connection: Microsoft365Connection,
        request: TeamsMeetingRequest
    ) -> TeamsMeetingResponse:
        """Create a Teams meeting."""
        endpoint = "/me/onlineMeetings"
        
        data = {
            "startDateTime": request.start_time.isoformat(),
            "endDateTime": request.end_time.isoformat(),
            "subject": request.title
        }
        
        if request.description:
            data["description"] = request.description
        
        if request.attendees:
            data["participants"] = {
                "attendees": [{"emailAddress": {"address": email}} for email in request.attendees]
            }
        
        result = self._make_request(connection, "POST", endpoint, data)
        
        return TeamsMeetingResponse(
            id=result.get("id"),
            join_url=result.get("joinUrl"),
            start_time=request.start_time,
            end_time=request.end_time
        )
    
    def send_teams_message(
        self,
        connection: Microsoft365Connection,
        channel_id: str,
        message: str
    ) -> Dict[str, Any]:
        """Send a message to a Teams channel."""
        endpoint = f"/teams/{connection.settings.get('team_id')}/channels/{channel_id}/messages"
        
        data = {
            "body": {
                "contentType": "html",
                "content": message
            }
        }
        
        return self._make_request(connection, "POST", endpoint, data)
    
    def create_sharepoint_folder(
        self,
        connection: Microsoft365Connection,
        request: SharePointFolderRequest
    ) -> Dict[str, Any]:
        """Create a SharePoint folder."""
        site_id = connection.settings.get("site_id")
        drive_id = connection.settings.get("drive_id")
        
        if request.parent_folder_id:
            endpoint = f"/sites/{site_id}/drives/{drive_id}/items/{request.parent_folder_id}/children"
        else:
            endpoint = f"/sites/{site_id}/drives/{drive_id}/root/children"
        
        data = {
            "name": request.folder_name,
            "folder": {},
            "@microsoft.graph.conflictBehavior": "rename"
        }
        
        return self._make_request(connection, "POST", endpoint, data)
    
    def upload_sharepoint_file(
        self,
        connection: Microsoft365Connection,
        folder_id: str,
        file_name: str,
        file_content: bytes
    ) -> Dict[str, Any]:
        """Upload a file to SharePoint."""
        site_id = connection.settings.get("site_id")
        drive_id = connection.settings.get("drive_id")
        
        endpoint = f"/sites/{site_id}/drives/{drive_id}/items/{folder_id}:/{file_name}:/content"
        
        access_token = connection.access_token
        if datetime.utcnow() >= connection.token_expires_at:
            access_token = self._refresh_token(connection)
        
        url = f"{MICROSOFT_GRAPH_BASE_URL}{endpoint}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/octet-stream"
        }
        
        response = requests.put(url, headers=headers, data=file_content)
        response.raise_for_status()
        return response.json()
    
    def create_outlook_event(
        self,
        connection: Microsoft365Connection,
        request: OutlookEventRequest
    ) -> Dict[str, Any]:
        """Create an Outlook calendar event."""
        endpoint = "/me/events"
        
        data = {
            "subject": request.subject,
            "start": {
                "dateTime": request.start_time.isoformat(),
                "timeZone": "UTC"
            },
            "end": {
                "dateTime": request.end_time.isoformat(),
                "timeZone": "UTC"
            }
        }
        
        if request.attendees:
            data["attendees"] = [{"emailAddress": {"address": email}} for email in request.attendees]
        
        if request.location:
            data["location"] = {"displayName": request.location}
        
        if request.body:
            data["body"] = {"contentType": "HTML", "content": request.body}
        
        return self._make_request(connection, "POST", endpoint, data)
    
    def get_user_profile(
        self,
        connection: Microsoft365Connection
    ) -> Dict[str, Any]:
        """Get connected user's profile."""
        return self._make_request(connection, "GET", "/me")
    
    def get_teams_channels(
        self,
        connection: Microsoft365Connection
    ) -> List[Dict[str, Any]]:
        """Get Teams channels."""
        team_id = connection.settings.get("team_id")
        endpoint = f"/teams/{team_id}/channels"
        
        result = self._make_request(connection, "GET", endpoint)
        return result.get("value", [])
    
    def sync_project_to_teams(
        self,
        connection: Microsoft365Connection,
        project_id: str,
        project_name: str
    ) -> Dict[str, Any]:
        """Create Teams channel for a project."""
        team_id = connection.settings.get("team_id")
        endpoint = f"/teams/{team_id}/channels"
        
        data = {
            "displayName": project_name[:50],  # Teams limit
            "description": f"Project channel for {project_name}",
            "membershipType": "standard"
        }
        
        return self._make_request(connection, "POST", endpoint, data)
    
    def send_project_notification(
        self,
        connection: Microsoft365Connection,
        channel_id: str,
        notification_type: str,
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Send project notification to Teams."""
        # Format message based on notification type
        if notification_type == "task_assigned":
            message = f"""
            <h3>New Task Assigned</h3>
            <p><b>Task:</b> {data.get('task_title')}</p>
            <p><b>Assigned to:</b> {data.get('assignee_name')}</p>
            <p><b>Due:</b> {data.get('due_date')}</p>
            """
        elif notification_type == "rfi_created":
            message = f"""
            <h3>New RFI Submitted</h3>
            <p><b>Subject:</b> {data.get('rfi_subject')}</p>
            <p><b>From:</b> {data.get('submitter_name')}</p>
            """
        else:
            message = f"<p>{data.get('message', 'New notification')}</p>"
        
        return self.send_teams_message(connection, channel_id, message)

# ---------------------------------------------------------------------------
# Store block facade (adapter glue over the ported donor service)
# ---------------------------------------------------------------------------


class _ConnStore:
    """Minimal in-process stand-in for the donor's SQLAlchemy session."""

    def __init__(self):
        self.connections: Dict[str, Microsoft365Connection] = {}

    def add(self, obj):
        self.connections[str(obj.id)] = obj

    def commit(self):
        return {"persisted": False, "note": "in-process store — nothing to commit"}

    def refresh(self, obj):
        return obj


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "microsoft_365", "status": status, "result": result, "error": error, "detail": detail}


def _token_usable(connection: Microsoft365Connection, now: datetime) -> bool:
    if connection.access_token is None:
        return False
    if connection.token_expires_at is None:
        return True
    return now < connection.token_expires_at


class Microsoft365Block(UniversalBlock):
    """Microsoft 365 Graph integration ported from Cerebrum."""

    name = "microsoft_365"
    version = "1.0.0"
    description = (
        "real: Microsoft 365 Graph integration (Teams meetings/messages, "
        "SharePoint folders/files, Outlook calendar events) ported from "
        "Cerebrum backend/app/integrations/microsoft_365.py. The donor's "
        "SQLAlchemy connection model is held in-process instead; requests go "
        "to graph.microsoft.com only when a connection carries a usable token. "
        "Unconfigured calls fail closed with a structured refusal."
    )
    layer = 3
    tags = ["microsoft365", "teams", "sharepoint", "outlook", "graph", "connector", "enterprise"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "create_connection", "organization_id": "tenant-guid", "access_token": "...", "token_expires_at": "2026-12-31T00:00:00", "settings": {"team_id": "t", "site_id": "s", "drive_id": "d"}}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    def __init__(self, hal_block=None, config: Dict[str, Any] = None):
        super().__init__(hal_block=hal_block, config=config)
        self._store = _ConnStore()
        self._service = Microsoft365Service(
            self._store,
            os.getenv("MICROSOFT365_CLIENT_ID", ""),
            os.getenv("MICROSOFT365_CLIENT_SECRET", ""),
        )

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "status")).lower()
        try:
            if action == "status":
                return _envelope("ok", {"service": "microsoft_365", "scopes": Microsoft365Service.SCOPES, "connections": len(self._store.connections)})
            if action == "create_connection":
                return self._create_connection(payload)
            if action == "get_connection":
                return self._get_connection(payload)
            conn = self._resolve(payload)
            if conn is None:
                return _envelope("error", error="connection not found", detail={"action": action})
            if not conn.is_active:
                return _envelope("refused", error="connection is inactive", detail={"connection_id": conn.id})
            if action == "create_teams_meeting":
                return self._call(action, conn, payload)
            if action == "send_teams_message":
                return self._call(action, conn, payload)
            if action == "create_sharepoint_folder":
                return self._call(action, conn, payload)
            if action == "upload_sharepoint_file":
                return self._call(action, conn, payload)
            if action == "create_outlook_event":
                return self._call(action, conn, payload)
            if action == "get_user_profile":
                return self._call(action, conn, payload)
            if action == "get_teams_channels":
                return self._call(action, conn, payload)
            if action == "sync_project_to_teams":
                return self._call(action, conn, payload)
            if action == "send_project_notification":
                return self._call(action, conn, payload)
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["status", "create_connection", "get_connection", "create_teams_meeting", "send_teams_message", "create_sharepoint_folder", "upload_sharepoint_file", "create_outlook_event", "get_user_profile", "get_teams_channels", "sync_project_to_teams", "send_project_notification"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)

    # -- internals ---------------------------------------------------------

    def _create_connection(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        conn_id = str(payload.get("connection_id") or payload.get("id") or f"conn-{len(self._store.connections) + 1}")
        if conn_id in self._store.connections:
            return _envelope("error", error="connection id already exists", detail={"connection_id": conn_id})
        try:
            conn = Microsoft365Connection(
                id=conn_id,
                tenant_id=payload.get("tenant_id"),
                project_id=payload.get("project_id"),
                organization_id=str(payload.get("organization_id", "")),
                organization_name=payload.get("organization_name"),
                access_token=payload.get("access_token"),
                refresh_token=payload.get("refresh_token"),
                token_expires_at=payload.get("token_expires_at"),
                scopes=payload.get("scopes") or [],
                connected_by=payload.get("connected_by"),
                is_active=bool(payload.get("is_active", True)),
                settings=payload.get("settings") if isinstance(payload.get("settings"), dict) else {},
            )
        except Exception as exc:
            return _envelope("error", error=f"invalid connection payload: {exc}", detail={"type": type(exc).__name__})
        self._store.add(conn)
        return _envelope("ok", {"connection": conn.model_dump(mode="json")})

    def _get_connection(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        conn = self._store.connections.get(str(payload.get("connection_id", "")))
        if conn is None:
            return _envelope("error", error="connection not found", detail={"connection_id": payload.get("connection_id")})
        return _envelope("ok", {"connection": conn.model_dump(mode="json")})

    def _resolve(self, payload: Dict[str, Any]) -> Optional[Microsoft365Connection]:
        conn_id = str(payload.get("connection_id", ""))
        return self._store.connections.get(conn_id)

    def _call(self, action: str, conn: Microsoft365Connection, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Fail-closed credential gate: refuse before any network request when
        # there is no usable token, and refuse a refresh when the client
        # credentials needed for it are not configured.
        now = datetime.utcnow()
        if not _token_usable(conn, now):
            if not conn.refresh_token:
                return _envelope("refused", error="no usable access token and no refresh token", detail={"connection_id": conn.id, "action": action})
            if not (self._service.client_id and self._service.client_secret):
                return _envelope("refused", error="access token expired and OAuth client credentials are not configured (MICROSOFT365_CLIENT_ID/MICROSOFT365_CLIENT_SECRET)", detail={"connection_id": conn.id, "action": action})
        if action == "create_teams_meeting":
            req = TeamsMeetingRequest(**payload.get("meeting", {}))
            resp = self._service.create_teams_meeting(conn, req)
            return _envelope("ok", {"meeting": resp.model_dump(mode="json")})
        if action == "send_teams_message":
            if not conn.settings.get("team_id"):
                return _envelope("refused", error="connection settings must carry team_id for Teams messages", detail={"connection_id": conn.id})
            result = self._service.send_teams_message(conn, str(payload.get("channel_id", "")), str(payload.get("message", "")))
            return _envelope("ok", {"sent": result})
        if action == "create_sharepoint_folder":
            if not (conn.settings.get("site_id") and conn.settings.get("drive_id")):
                return _envelope("refused", error="connection settings must carry site_id and drive_id for SharePoint", detail={"connection_id": conn.id})
            req = SharePointFolderRequest(**payload.get("folder", {}))
            result = self._service.create_sharepoint_folder(conn, req)
            return _envelope("ok", {"folder": result})
        if action == "upload_sharepoint_file":
            if not (conn.settings.get("site_id") and conn.settings.get("drive_id")):
                return _envelope("refused", error="connection settings must carry site_id and drive_id for SharePoint", detail={"connection_id": conn.id})
            content = payload.get("file_content")
            if isinstance(content, str):
                content = content.encode("utf-8")
            if not isinstance(content, bytes):
                return _envelope("error", error="upload_sharepoint_file requires file_content bytes (or a str)")
            result = self._service.upload_sharepoint_file(conn, str(payload.get("folder_id", "")), str(payload.get("file_name", "")), content)
            return _envelope("ok", {"uploaded": result})
        if action == "create_outlook_event":
            req = OutlookEventRequest(**payload.get("event", {}))
            result = self._service.create_outlook_event(conn, req)
            return _envelope("ok", {"event": result})
        if action == "get_user_profile":
            return _envelope("ok", {"profile": self._service.get_user_profile(conn)})
        if action == "get_teams_channels":
            if not conn.settings.get("team_id"):
                return _envelope("refused", error="connection settings must carry team_id for Teams channels", detail={"connection_id": conn.id})
            return _envelope("ok", {"channels": self._service.get_teams_channels(conn)})
        if action == "sync_project_to_teams":
            if not conn.settings.get("team_id"):
                return _envelope("refused", error="connection settings must carry team_id for Teams sync", detail={"connection_id": conn.id})
            result = self._service.sync_project_to_teams(conn, str(payload.get("project_id", "")), str(payload.get("project_name", "")))
            return _envelope("ok", {"synced": result})
        if action == "send_project_notification":
            if not conn.settings.get("team_id"):
                return _envelope("refused", error="connection settings must carry team_id for Teams notifications", detail={"connection_id": conn.id})
            result = self._service.send_project_notification(conn, str(payload.get("channel_id", "")), str(payload.get("notification_type", "")), payload.get("data") if isinstance(payload.get("data"), dict) else {})
            return _envelope("ok", {"notification": result})
        return _envelope("error", error=f"unhandled action: {action}")
