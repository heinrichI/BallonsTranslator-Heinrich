"""Tests for DIContainer."""
import pytest
from ui.di_container import DIContainer


class TestDIContainer:
    def setup_method(self):
        DIContainer.reset()

    def test_register_resolve(self):
        class IMyService:
            pass

        class MyService(IMyService):
            pass

        service = MyService()
        DIContainer.register(IMyService, service)

        resolved = DIContainer.resolve(IMyService)
        assert resolved is service

    def test_resolve_unregistered(self):
        class IUnknown:
            pass

        with pytest.raises(KeyError):
            DIContainer.resolve(IUnknown)

    def test_try_resolve(self):
        class IOptional:
            pass

        assert DIContainer.try_resolve(IOptional) is None

    def test_is_registered(self):
        class ICheck:
            pass

        assert not DIContainer.is_registered(ICheck)
        DIContainer.register(ICheck, object())
        assert DIContainer.is_registered(ICheck)

    def test_reset(self):
        class IReset:
            pass

        DIContainer.register(IReset, object())
        DIContainer.reset()
        assert not DIContainer.is_registered(IReset)

    def test_get_all(self):
        class IA:
            pass
        class IB:
            pass

        a, b = object(), object()
        DIContainer.register(IA, a)
        DIContainer.register(IB, b)

        all_deps = DIContainer.get_all()
        assert IA in all_deps
        assert IB in all_deps
        assert all_deps[IA] is a
