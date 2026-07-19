"""
DIContainer — простой DI контейнер (Service Locator).

Паттерн Service Locator для управления зависимостями.
"""

from typing import Dict, Any, Optional, Type


class DIContainer:
    """
    Простой DI контейнер.

    Responsibilities:
    - Регистрация зависимостей по интерфейсу
    - Получение зависимостей по интерфейсу
    - Сброс контейнера (для тестов)
    """

    _instances: Dict[type, Any] = {}

    @classmethod
    def register(cls, interface: type, implementation: Any) -> None:
        """
        Регистрирует реализацию для интерфейса.

        Args:
            interface: Тип интерфейса (класс или Protocol)
            implementation: Экземпляр реализации
        """
        cls._instances[interface] = implementation

    @classmethod
    def resolve(cls, interface: type) -> Any:
        """
        Возвращает реализацию для интерфейса.

        Args:
            interface: Тип интерфейса

        Returns:
            Экземпляр реализации

        Raises:
            KeyError: Если интерфейс не зарегистрирован
        """
        impl = cls._instances.get(interface)
        if impl is None:
            raise KeyError(f"{interface.__name__} not registered")
        return impl

    @classmethod
    def try_resolve(cls, interface: type) -> Optional[Any]:
        """
        Пытается получить реализацию для интерфейса.

        Args:
            interface: Тип интерфейса

        Returns:
            Экземпляр реализации или None
        """
        return cls._instances.get(interface)

    @classmethod
    def is_registered(cls, interface: type) -> bool:
        """
        Проверяет, зарегистрирован ли интерфейс.

        Args:
            interface: Тип интерфейса

        Returns:
            True если зарегистрирован
        """
        return interface in cls._instances

    @classmethod
    def reset(cls) -> None:
        """Сбрасывает контейнер (для тестов)."""
        cls._instances.clear()

    @classmethod
    def get_all(cls) -> Dict[type, Any]:
        """Возвращает все зарегистрированные зависимости."""
        return cls._instances.copy()
