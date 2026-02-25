import inspect
from hummingbot.connector.exchange_py_base import ExchangePyBase
# Check if budget_checker is a property (descriptor) or instance attribute
for cls in inspect.getmro(ExchangePyBase):
    if "budget_checker" in cls.__dict__:
        obj = cls.__dict__["budget_checker"]
        print(f"Found in {cls.__name__}: {type(obj)}")
        if isinstance(obj, property):
            print("  -> It's a @property — CANNOT be replaced on instance")
        else:
            print("  -> It's an attribute — CAN be replaced on instance")
        break
else:
    print("budget_checker not found in any parent class __dict__")
    print("It may be set in __init__ as self._budget_checker")

# Also check the connector_base
from hummingbot.connector.connector_base import ConnectorBase
for cls in inspect.getmro(ConnectorBase):
    if "budget_checker" in cls.__dict__:
        obj = cls.__dict__["budget_checker"]
        print(f"ConnectorBase chain: Found in {cls.__name__}: {type(obj)}")
        break
