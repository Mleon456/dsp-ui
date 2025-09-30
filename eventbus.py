from collections import defaultdict
from typing import Callable, Any

class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[[Any], None]]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Callable[[Any], None]) -> None:
        self._subs[topic].append(handler)

    def publish(self, topic: str, payload: Any) -> None:
        for h in list(self._subs.get(topic, [])):
            try:
                h(payload)
            except Exception as e:
                print(f"[bus] handler error on {topic}: {e}")
