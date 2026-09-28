from types import SimpleNamespace
from unittest.mock import Mock

from lock_in.platform.windows.window_activation import SW_RESTORE, WindowActivator


def activator(*, valid=True, iconic=False, accepted=True):
    api = SimpleNamespace(
        IsWindow=Mock(return_value=valid),
        IsIconic=Mock(return_value=iconic),
        ShowWindowAsync=Mock(return_value=True),
        SetForegroundWindow=Mock(return_value=accepted),
        GetForegroundWindow=Mock(return_value=99),
    )
    adapter = WindowActivator.__new__(WindowActivator)
    adapter._user32 = api
    return adapter, api


def test_minimized_target_is_restored_asynchronously():
    adapter, api = activator(iconic=True)
    assert adapter.activate(20)
    api.ShowWindowAsync.assert_called_once_with(20, SW_RESTORE)


def test_denied_activation_does_not_attach_external_input_queues():
    # The fake intentionally has no AttachThreadInput/BringWindowToTop APIs.
    adapter, api = activator(accepted=False)
    assert not adapter.activate(20)
    api.SetForegroundWindow.assert_called_once_with(20)


def test_gone_window_is_not_activated():
    adapter, api = activator(valid=False)
    assert not adapter.activate(20)
    assert not adapter.activate(None)
    api.SetForegroundWindow.assert_not_called()
