"""
WAFR - Well-Architected Framework Review System

A multi-agent AI system for automated AWS Well-Architected Framework assessments.

NOTE: This module uses lazy imports to avoid circular dependency issues.
Import specific components directly from their modules for best performance.
"""

__version__ = "1.0.0"

# Lazy imports - only load when accessed
_lazy_imports = {
    # Orchestrator
    "create_orchestrator": "wafr.agents.orchestrator",
    "WafrOrchestrator": "wafr.agents.orchestrator",
    # Production Orchestrator
    "ProductionOrchestrator": "wafr.agents.production_orchestrator",
    "create_production_orchestrator": "wafr.agents.production_orchestrator",
    # AG-UI
    "create_agui_orchestrator": "wafr.ag_ui.orchestrator_integration",
}

__all__ = [
    "__version__",
    "create_orchestrator",
    "WafrOrchestrator",
    "ProductionOrchestrator",
    "create_production_orchestrator",
    "create_agui_orchestrator",
]


def __getattr__(name):
    """Lazy import handler - imports modules only when accessed."""
    if name in _lazy_imports:
        module_path = _lazy_imports[name]
        import importlib
        try:
            module = importlib.import_module(module_path)
            return getattr(module, name)
        except ImportError:
            # Allow module to load even if component isn't available
            raise AttributeError(f"module 'wafr' has no attribute '{name}' (import failed)")
    raise AttributeError(f"module 'wafr' has no attribute '{name}'")
