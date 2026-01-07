__all__ = ["create_app"]


def __getattr__(name: str):
	if name == "create_app":
		from .app import create_app

		return create_app
	raise AttributeError(name)
