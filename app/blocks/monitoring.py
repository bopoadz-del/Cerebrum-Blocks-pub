from app.core.universal_base import UniversalBlock
from typing import Dict, Any, List, Optional
import time
import statistics
from collections import deque, defaultdict
from datetime import datetime, timedelta, timezone
import json

class MonitoringBlock(UniversalBlock):
    """
    Provider leaderboard. Providers are registered, never assumed.
    Call add_provider. No vendor is built in.
    Scores live in process memory and are lost on restart.
    """
    
    name = "monitoring"
    version = "1.0.0"
    requires = ["config", "memory"]  # Uses Memory Block for metrics storage
    layer = 2  # Monitoring layer
    tags = ["monitoring", "observability", "core"]
    default_config = {
        "track_providers": [],
        "window_size": 100,
        "prediction_threshold": 0.3
    }

    ui_schema = {
        'input': {'type': 'json', 'accept': None, 'placeholder': 'JSON payload for the selected action', 'multiline': True},
        'output': {'type': 'json', 'fields': [{'name': 'result', 'type': 'json', 'label': 'Result'}]},
        'params': [{'name': 'action', 'type': 'select', 'label': 'Action', 'options': ['record_call', 'leaderboard', 'provider_status', 'recommend', 'health_report', 'predictive_failover', 'add_provider'], 'default': 'record_call'}, {'name': 'track_providers', 'type': 'json', 'label': 'Track Providers', 'default': []}, {'name': 'window_size', 'type': 'number', 'label': 'Window Size', 'default': 100}, {'name': 'prediction_threshold', 'type': 'number', 'label': 'Prediction Threshold', 'default': 0.3}],
        'quick_actions': [],
    }
    
    def __init__(self, hal_block=None, config: Dict[str, Any] = None):
        super().__init__(hal_block, config)
        self.memory_block = None  # Wired by assembler
        
        # Empty until add_provider or track_providers supplies ids. No vendor default.
        self.providers = {}
        
        # Metrics window (last 100 calls per provider)
        self.metrics_window = 100
        self.latency_history = defaultdict(lambda: deque(maxlen=self.metrics_window))
        self.error_history = defaultdict(lambda: deque(maxlen=self.metrics_window))
        self.uptime_history = defaultdict(lambda: deque(maxlen=self.metrics_window))
        
        # Reliability scores (0-100)
        self.reliability_scores = {}
        for provider_id in (self.config or {}).get("track_providers") or []:
            if isinstance(provider_id, str) and provider_id:
                self.add_provider(provider_id)
        
        # Auto-routing threshold
        self.degraded_threshold = 70  # Below 70% = avoid
        self.critical_threshold = 40   # Below 40% = emergency only
        
        self.last_leaderboard_update = 0
        self.leaderboard_cache = None
    
    async def _legacy_initialize(self):
        """Initialize monitoring"""
        print("📊 Monitoring Block initialized")
        print("   Tracking:", list(self.providers.keys()))
        print("   Auto-route thresholds: Degraded <70%, Critical <40%")
        return True
    
    async def process(self, input_data: Dict, params: Dict = None) -> Dict:
        """Monitoring operations"""
        action = (params or {}).get("action") or (input_data.get("action") if isinstance(input_data, dict) else None)
        
        if action == "record_call":
            return await self._record_call(input_data)
        elif action == "leaderboard":
            return await self._get_leaderboard()
        elif action == "provider_status":
            return await self._get_provider_status(input_data.get("provider"))
        elif action == "recommend":
            return await self._recommend_provider()
        elif action == "health_report":
            return await self._health_report()
        elif action == "predictive_failover":
            return await self._predictive_analysis()
        elif action == "add_provider":
            info = input_data.get("info") if isinstance(input_data.get("info"), dict) else None
            return self.add_provider(input_data.get("provider"), info)
        
        return {"error": f"Unknown action: {action}"}

    def add_provider(self, provider_id: Optional[str], info: Optional[Dict] = None) -> Dict:
        """Register a provider by id. Does not assume a vendor."""
        if not isinstance(provider_id, str) or not provider_id.strip():
            return {"status": "error", "error": "provider id required"}
        provider_id = provider_id.strip()
        meta = {"name": provider_id, "type": "unspecified", "region": "unspecified"}
        if info:
            for key in ("name", "type", "region"):
                if key in info and info[key]:
                    meta[key] = info[key]
        self.providers[provider_id] = meta
        self.reliability_scores.setdefault(provider_id, 100.0)
        self.leaderboard_cache = None
        return {"status": "ok", "provider": provider_id}
    
    async def _record_call(self, data: Dict) -> Dict:
        """Record API call metrics"""
        provider = data.get("provider")
        latency_ms = data.get("latency_ms", 0)
        success = data.get("success", True)
        error_type = data.get("error_type")
        timestamp = time.time()
        
        if provider not in self.providers:
            return {"error": "Unknown provider"}
        
        # Store in memory block for persistence
        if self.memory_block:
            await self.memory_block.process({
                "action": "set",
                "key": f"metrics:{provider}:{int(timestamp)}",
                "value": {
                    "latency": latency_ms,
                    "success": success,
                    "error": error_type,
                    "timestamp": timestamp
                },
                "ttl": 86400  # 24 hour retention
            })
        
        # Update in-memory windows
        self.latency_history[provider].append(latency_ms)
        self.error_history[provider].append(0 if success else 1)
        self.uptime_history[provider].append(1 if success else 0)
        
        # Recalculate reliability score
        await self._calculate_reliability(provider)
        
        return {"recorded": True, "provider": provider}
    
    async def _calculate_reliability(self, provider: str):
        """Calculate provider reliability score (0-100)"""
        if not self.error_history[provider]:
            return
        
        # Error rate (weight: 50%)
        error_rate = sum(self.error_history[provider]) / len(self.error_history[provider])
        
        # Latency score (weight: 30%) - optimal is <500ms
        avg_latency = statistics.mean(self.latency_history[provider]) if self.latency_history[provider] else 0
        latency_score = max(0, 100 - (avg_latency / 10))  # 1000ms = 0 score
        
        # Uptime (weight: 20%)
        uptime_rate = statistics.mean(self.uptime_history[provider]) if self.uptime_history[provider] else 1
        
        # Composite score
        reliability = (uptime_rate * 50) + (latency_score * 0.30) + ((1 - error_rate) * 20)
        self.reliability_scores[provider] = round(reliability, 2)
        
        # Invalidate leaderboard cache
        self.leaderboard_cache = None
    
    async def _get_leaderboard(self) -> Dict:
        """Get provider leaderboard - ranked by reliability"""
        # Check cache (refresh every 60s)
        if self.leaderboard_cache and (time.time() - self.last_leaderboard_update) < 60:
            return self.leaderboard_cache
        
        leaderboard = []
        
        for provider_id, info in self.providers.items():
            score = self.reliability_scores[provider_id]
            latencies = list(self.latency_history[provider_id])
            errors = list(self.error_history[provider_id])
            
            # Determine status
            if score >= 90:
                status = "excellent"
                color = "green"
            elif score >= 70:
                status = "good"
                color = "yellow"
            elif score >= 40:
                status = "degraded"
                color = "orange"
            else:
                status = "critical"
                color = "red"
            
            leaderboard.append({
                "rank": 0,  # Set later
                "provider": provider_id,
                "name": info["name"],
                "type": info["type"],
                "region": info["region"],
                "reliability_score": score,
                "avg_latency_ms": round(statistics.mean(latencies), 2) if latencies else 0,
                "error_rate_percent": round(sum(errors) / len(errors) * 100, 2) if errors else 0,
                "total_calls": len(latencies),
                "status": status,
                "color": color,
                "recommendation": "use" if score >= 70 else "avoid" if score >= 40 else "emergency_only"
            })
        
        # Sort by reliability score (descending)
        leaderboard.sort(key=lambda x: x["reliability_score"], reverse=True)
        
        # Assign ranks
        for i, entry in enumerate(leaderboard):
            entry["rank"] = i + 1
        
        # Cache result
        self.leaderboard_cache = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "leaderboard": leaderboard,
            "top_provider": leaderboard[0]["provider"] if leaderboard else None,
            "auto_route_enabled": True
        }
        self.last_leaderboard_update = time.time()
        
        return self.leaderboard_cache
    
    async def _recommend_provider(self) -> Dict:
        """AI-powered provider recommendation based on current conditions"""
        leaderboard = (await self._get_leaderboard())["leaderboard"]
        
        if not leaderboard:
            return {
                "recommended": None,
                "confidence": None,
                "status": "error",
                "error": "no providers registered",
                "reason": "no providers registered",
            }
        
        # Find best available provider
        for entry in leaderboard:
            if entry["recommendation"] == "use":
                return {
                    "recommended": entry["provider"],
                    "confidence": entry["reliability_score"],
                    "reason": f"Best reliability at {entry['avg_latency_ms']}ms avg latency",
                    "fallback_sequence": [e["provider"] for e in leaderboard if e["recommendation"] in ["use", "avoid"]]
                }
        
        # If all degraded, use local
        return {
            "recommended": None,
            "confidence": None,
            "status": "error",
            "error": "no provider meets the use threshold",
            "reason": "no provider meets the use threshold",
        }
    
    async def _predictive_analysis(self) -> Dict:
        """Predict potential failures before they happen"""
        predictions = []
        
        for provider in self.providers:
            latencies = list(self.latency_history[provider])
            
            if len(latencies) >= 10:
                # Check for degrading trend (increasing latency)
                recent_avg = statistics.mean(latencies[-5:])
                older_avg = statistics.mean(latencies[-10:-5])
                
                if recent_avg > older_avg * 1.5:  # 50% increase
                    predictions.append({
                        "provider": provider,
                        "prediction": "latency_spike",
                        "severity": "medium",
                        "recommendation": f"Preemptively reroute {provider} traffic",
                        "confidence": 75
                    })
                
                # Check error rate trend
                recent_errors = sum(list(self.error_history[provider])[-10:])
                if recent_errors >= 3:  # 3 errors in last 10 calls
                    predictions.append({
                        "provider": provider,
                        "prediction": "impending_failure",
                        "severity": "high",
                        "recommendation": f"Switch {provider} to fallback immediately",
                        "confidence": 85
                    })
        
        return {
            "predictions": predictions,
            "preventive_actions_recommended": len(predictions) > 0,
            "analyzed_at": datetime.now(timezone.utc).isoformat()
        }
    
    async def _health_report(self) -> Dict:
        """Full system health report"""
        lb = await self._get_leaderboard()
        pred = await self._predictive_analysis()
        
        return {
            "overall_status": "healthy" if all(e["recommendation"] == "use" for e in lb["leaderboard"][:2]) else "degraded",
            "leaderboard": lb,
            "predictions": pred,
            "failover_readiness": "ready",
            "recommendation": await self._recommend_provider()
        }
    
    async def _get_provider_status(self, provider: Optional[str]) -> Dict:
        """Get specific provider status"""
        if not provider:
            return {"providers": {p: self.reliability_scores[p] for p in self.providers}}
        
        if provider not in self.providers:
            return {"error": "Unknown provider"}
        
        return {
            "provider": provider,
            "reliability_score": self.reliability_scores[provider],
            "metrics": {
                "latency_history": list(self.latency_history[provider])[-10:],
                "error_history": list(self.error_history[provider])[-10:]
            }
        }
    
    def health(self) -> Dict:
        h = {"name": self.name, "version": self.version}
        h["providers_tracked"] = len(self.providers)
        h["metrics_retention"] = f"{self.metrics_window} calls per provider"
        h["auto_route_enabled"] = True
        return h
