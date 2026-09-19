from lock_in.monitoring.foreground_service import ForegroundMonitoringService


class FakeMonitor:
    def __init__(self) -> None:
        self.started = False
        self.stop_timeout = None

    def start(self) -> None:
        self.started = True

    def stop(self, timeout: float) -> None:
        self.stop_timeout = timeout


def test_production_monitor_adapter_obeys_component_lifecycle() -> None:
    monitor = FakeMonitor()
    service = ForegroundMonitoringService(lambda _observation: None, monitor=monitor)

    service.start()
    service.stop(1.25)

    assert monitor.started
    assert monitor.stop_timeout == 1.25
