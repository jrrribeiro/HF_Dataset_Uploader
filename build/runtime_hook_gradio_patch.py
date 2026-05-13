import os

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

try:
    import gradio.component_meta as _component_meta

    def _noop_create_or_modify_pyi(*args, **kwargs):
        return None

    _component_meta.create_or_modify_pyi = _noop_create_or_modify_pyi
except Exception:
    pass
