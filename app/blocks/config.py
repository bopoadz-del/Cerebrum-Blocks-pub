"""Configuration Block - in-process defaults only.

Does not read config/blocks.json. Does not apply a CEREBRUM_ env prefix.
storage.data_dir reads DATA_DIR directly. State is lost on restart.
"""

from app.core.universal_base import UniversalBlock
from typing import Dict, Any
import os
import json


class ConfigBlock(UniversalBlock):
    """
    In-process defaults only.
    Does not read a config file and does not apply an env prefix.
    """
    
    name = "config"
    version = "1.0.0"
    requires = ["hal"]
    layer = 0  # Infrastructure - must initialize first
    tags = ["infrastructure", "core"]
    default_config = {
        "persistence": "in_process",
    }

    ui_schema = {
        'input': {'type': 'json', 'accept': None, 'placeholder': 'Config key/value payload', 'multiline': True},
        'output': {'type': 'json', 'fields': [{'name': 'result', 'type': 'json', 'label': 'Result'}]},
        'params': [{'name': 'action', 'type': 'select', 'label': 'Action', 'options': ['get', 'get_all', 'set'], 'default': 'get'}],
        'quick_actions': [],
    }
    
    def __init__(self, hal_block, config: Dict[str, Any]):
        super().__init__(hal_block, config)
        self.hal = hal_block
        self.configs = {}
        self._load_defaults()
    
    def _load_defaults(self):
        """Load default configurations based on hardware profile"""
        profile = self.hal.detect() if self.hal else None
        
        # Base config
        self.configs = {
            "chat": {
                "default_provider": "kimi",
                "providers": {
                    "kimi": {"model": "kimi-k2-0905-preview", "timeout": 30},
                },
                "streaming": True,
                "max_tokens": 1024,
            },
            "vector": {
                "backend": "chroma",
                "collection": "default",
                "embedding_model": "all-MiniLM-L6-v2",
                "dimension": 384,
            },
            "storage": {
                "backend": "local",
                "data_dir": os.getenv("DATA_DIR", "./data"),
            },
            "memory": {
                "max_size": 10000,
                "default_ttl": 3600,
            },
            "monitoring": {
                "enabled": True,
                "metrics_window": 100,
            },
            "auth": {
                "rate_limit_default": 100,
                "rate_limit_window": 60,
            }
        }
        
        # Adjust for hardware profile
        if profile:
            if "edge" in profile.value:
                # Edge optimizations
                self.configs["chat"]["default_provider"] = "local_ollama"
                self.configs["vector"]["backend"] = "memory"
                self.configs["memory"]["max_size"] = 1000
            elif "embedded" in profile.value:
                # Minimal config
                self.configs["chat"]["default_provider"] = "kimi"
                self.configs["vector"]["backend"] = "memory"
                self.configs["memory"]["max_size"] = 100
    
    async def _legacy_initialize(self):
        """Initialize config"""
        print(f"⚙️  Config Block initialized")
        print(f"   Loaded configs for: {list(self.configs.keys())}")
        return True
    
    async def process(self, input_data: Dict, params: Dict = None) -> Dict:
        """Get or set configuration"""
        action = (params or {}).get("action") or (input_data.get("action") if isinstance(input_data, dict) else None)
        
        if action == "get":
            block = input_data.get("block")
            return self.configs.get(block, {})
        elif action == "get_all":
            return self.configs
        elif action == "set":
            block = input_data.get("block")
            key = input_data.get("key")
            value = input_data.get("value")
            if block not in self.configs:
                self.configs[block] = {}
            self.configs[block][key] = value
            return {"set": True, "block": block, "key": key}
        
        return {"error": f"Unknown action: {action}"}
    
    def get_block_config(self, block_name: str) -> Dict[str, Any]:
        """Get configuration for a specific block"""
        return self.configs.get(block_name, {})
    
    def health(self) -> Dict[str, Any]:
        """Health check"""
        h = {"name": self.name, "version": self.version}
        h["configs_loaded"] = len(self.configs)
        h["persistence"] = "in_process"
        h["config_file_read"] = False
        h["env_prefix_applied"] = False
        h["hardware_profile"] = self.hal.detect().value if self.hal else "unknown"
        return h
