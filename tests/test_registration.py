import os
import uuid

import pytest

from lock_in.distribution.installer import UserRegistry


@pytest.mark.skipif(os.name != "nt", reason="Windows registry views")
def test_real_registry_views_can_be_registered_and_removed_without_touching_chrome():
    # A unique test-only key; real NativeMessagingHosts keys are never touched.
    path = rf"Software\LockIn-Test-{uuid.uuid4().hex}"
    registry = UserRegistry({"chrome": path})
    try:
        assert registry.read("chrome") == [None, None]
        registry.write("chrome", [r"C:\test\manifest.json"] * 2)
        assert registry.read("chrome") == [r"C:\test\manifest.json"] * 2
    finally:
        registry.write("chrome", [None, None])
    assert registry.read("chrome") == [None, None]
