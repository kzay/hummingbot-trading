import tempfile
import types

from services.signal_service import model_loader


class _FakeJoblib:
    @staticmethod
    def load(path):
        return {"loaded_from": path}


def test_load_model_sklearn_joblib_with_fake_joblib(monkeypatch):
    monkeypatch.setattr(model_loader, "joblib", _FakeJoblib())
    with tempfile.NamedTemporaryFile(suffix=".joblib") as tmp:
        loaded = model_loader.load_model(
            runtime="sklearn_joblib",
            model_uri=tmp.name,
            timeout_sec=1,
        )
    assert loaded.runtime == "sklearn_joblib"
    assert loaded.model["loaded_from"]


def test_load_model_custom_python(monkeypatch):
    class CustomModel:
        version = "v-test"

        def load(self, _path):
            return None

        def predict(self, features):
            return 0.01

    fake_module = types.SimpleNamespace(CustomModel=CustomModel)
    monkeypatch.setattr(model_loader.importlib, "import_module", lambda _name: fake_module)
    loaded = model_loader.load_model(
        runtime="custom_python",
        model_uri="dummy.bin",
        custom_class_path="fake.module:CustomModel",
        timeout_sec=1,
    )
    assert loaded.runtime == "custom_python"
    assert loaded.model_version == "v-test"

