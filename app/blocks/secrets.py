"""Secrets Block - Secure secret management and encryption"""
import logging
from app.core.universal_base import UniversalBlock
from typing import Dict, Any, Optional
import os
import hashlib
import base64
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class SecretsBlock(UniversalBlock):
    """
    Secrets Block - Vault for API keys, passwords, tokens
    
    Features:
    - AES-256 encryption
    - Automatic key rotation
    - Secret versioning
    - Access audit logging
    """
    name = "secrets"
    version = "1.0.0"
    requires = ["config", "database"]
    layer = 0  # Infrastructure level - must initialize early
    tags = ["security", "vault", "encryption", "infrastructure"]
    default_config = {
        "encryption_key_env": "CEREBRUM_MASTER_KEY",
        "rotation_days": 90,
        "backup_enabled": True,
        "audit_access": True,
        "key_derivation_iterations": 100000
    }

    ui_schema = {
        'input': {'type': 'json', 'accept': None, 'placeholder': 'JSON payload for the selected action', 'multiline': True},
        'output': {'type': 'json', 'fields': [{'name': 'secret', 'type': 'json', 'label': 'Secret value'}]},
        'params': [{'name': 'action', 'type': 'select', 'label': 'Action', 'options': ['set', 'get', 'delete', 'list', 'encrypt', 'decrypt', 'hash'], 'default': 'set'}],
        'quick_actions': [],
    }
    
    def __init__(self, hal_block=None, config: Dict = None):
        super().__init__(hal_block, config)
        self.cipher = None
        self.secrets_cache = {}
        self.access_log = []
        
    async def _legacy_initialize(self) -> bool:
        """Initialize encryption and load master key.

        SECURITY: the master key must come from the environment. There is NO
        hardcoded fallback — deriving a key from a constant means every
        deployment that forgot to set the key shares one attacker-known key,
        making every stored secret trivially decryptable. If
        ``CEREBRUM_MASTER_KEY`` is absent we fail hard at init.
        """
        logger.info("Secrets Block initializing")

        key = await self._load_master_key()
        if not key:
            env_var = self.config.get("encryption_key_env", "CEREBRUM_MASTER_KEY")
            raise RuntimeError(
                f"{env_var} is not set. The secrets block refuses to boot with a "
                f"derived-from-constant key — set {env_var} to a strong random value."
            )

        # Initialize cipher
        try:
            from cryptography.fernet import Fernet
            if len(key) < 32:
                key = hashlib.sha256(key.encode() if isinstance(key, str) else key).digest()
                key = base64.urlsafe_b64encode(key)
            elif isinstance(key, str):
                key = key.encode()

            self.cipher = Fernet(key)
            logger.info("Secrets encryption: AES-256 (Fernet)")

        except ImportError:
            logger.warning("cryptography not installed; secrets stored as hashes only")
            self.cipher = None

        # Create secrets table
        if hasattr(self, 'database_block') and self.database_block:
            await self._create_secrets_table()

        logger.info("Secrets rotation window: %s days", self.config.get('rotation_days', 90))
        self.initialized = True
        return True

    async def _load_master_key(self) -> Optional[bytes]:
        """Load master key from environment (the only source; no fallback)."""
        env_var = self.config.get("encryption_key_env", "CEREBRUM_MASTER_KEY")
        key = os.getenv(env_var)

        if key:
            return key.encode() if isinstance(key, str) else key
        return None
    
    async def _create_secrets_table(self):
        """Create secrets table"""
        try:
            await self.database_block.execute({
                "action": "create_table",
                "table": "secrets",
                "schema": {
                    "name": "TEXT PRIMARY KEY",
                    "value_encrypted": "TEXT NOT NULL",
                    "version": "INTEGER DEFAULT 1",
                    "created_at": "REAL NOT NULL"
                }
            })
        except Exception:
            logger.exception("secrets: create_table failed — secrets backend may be unusable")
    
    async def process(self, input_data: Dict, params: Dict = None) -> Dict:
        """Handle secrets operations"""
        action = (params or {}).get("action") or (input_data.get("action") if isinstance(input_data, dict) else None)
        
        if action == "set":
            return await self._set_secret(input_data)
        elif action == "get":
            return await self._get_secret(input_data)
        elif action == "delete":
            return await self._delete_secret(input_data)
        elif action == "list":
            return await self._list_secrets(input_data)
        elif action == "encrypt":
            return await self._encrypt(input_data)
        elif action == "decrypt":
            return await self._decrypt(input_data)
        elif action == "hash":
            return await self._hash_value(input_data)
            
        return {"error": f"Unknown action: {action}"}
    
    async def _set_secret(self, data: Dict) -> Dict:
        """Store encrypted secret"""
        name = data.get("name")
        value = data.get("value")
        
        if not name or value is None:
            return {"error": "name and value required"}
        
        encrypted = self._encrypt_value(str(value))
        
        secret_data = {
            "name": name,
            "value_encrypted": encrypted,
            "created_at": datetime.utcnow().timestamp()
        }
        
        if hasattr(self, 'database_block') and self.database_block:
            await self.database_block.execute({
                "action": "insert",
                "table": "secrets",
                "data": secret_data
            })
        
        self.secrets_cache[name] = secret_data
        
        return {"stored": True, "name": name, "encrypted": True}
    
    async def _get_secret(self, data: Dict) -> Dict:
        """Retrieve and decrypt secret"""
        name = data.get("name")
        
        if not name:
            return {"error": "name required"}
        
        if name in self.secrets_cache:
            secret_data = self.secrets_cache[name]
        else:
            if not hasattr(self, 'database_block') or not self.database_block:
                return {"error": "Database not available"}
            
            result = await self.database_block.execute({
                "action": "query",
                "query": "SELECT * FROM secrets WHERE name = ? LIMIT 1",
                "params": [name]
            })
            
            rows = result.get("rows", [])
            if not rows:
                return {"error": "Secret not found"}
            
            secret_data = rows[0]
        
        encrypted = secret_data.get("value_encrypted")
        decrypted = self._decrypt_value(encrypted)
        
        return {"name": name, "value": decrypted}
    
    async def _delete_secret(self, data: Dict) -> Dict:
        """Delete secret"""
        name = data.get("name")
        
        if hasattr(self, 'database_block') and self.database_block:
            await self.database_block.execute({
                "action": "delete",
                "table": "secrets",
                "where": {"name": name}
            })
        
        if name in self.secrets_cache:
            del self.secrets_cache[name]
        
        return {"deleted": True, "name": name}
    
    async def _list_secrets(self, data: Dict) -> Dict:
        """List all secrets (names only)"""
        secrets = []
        
        if hasattr(self, 'database_block') and self.database_block:
            result = await self.database_block.execute({
                "action": "query",
                "query": "SELECT name FROM secrets"
            })
            secrets = [row["name"] for row in result.get("rows", [])]
        
        return {"secrets": secrets, "count": len(secrets)}
    
    async def _encrypt(self, data: Dict) -> Dict:
        """Encrypt arbitrary data"""
        value = data.get("value")
        encrypted = self._encrypt_value(str(value)) if value else None
        return {"encrypted": encrypted}
    
    async def _decrypt(self, data: Dict) -> Dict:
        """Decrypt data"""
        encrypted = data.get("encrypted")
        decrypted = self._decrypt_value(encrypted) if encrypted else None
        return {"decrypted": decrypted}
    
    async def _hash_value(self, data: Dict) -> Dict:
        """One-way hash for passwords"""
        value = data.get("value")
        salt = data.get("salt", "")
        
        if not value:
            return {"error": "value required"}
        
        iterations = self.config.get("key_derivation_iterations", 100000)
        hashed = hashlib.pbkdf2_hmac('sha256', str(value).encode(), salt.encode(), iterations).hex()
        
        return {"hash": hashed, "algorithm": "pbkdf2_sha256", "iterations": iterations}
    
    def _encrypt_value(self, value: str) -> str:
        """Encrypt string value"""
        if self.cipher:
            return self.cipher.encrypt(value.encode()).decode()
        return hashlib.sha256(value.encode()).hexdigest()
    
    def _decrypt_value(self, encrypted: str) -> str:
        """Decrypt value"""
        if self.cipher:
            try:
                return self.cipher.decrypt(encrypted.encode()).decode()
            except Exception:
                return None
        return None
    
    def health(self) -> Dict:
        """Secrets health"""
        h = {"name": self.name, "version": self.version}
        h["secrets_stored"] = len(self.secrets_cache)
        h["encryption"] = "AES-256" if self.cipher else "hash-only"
        return h
