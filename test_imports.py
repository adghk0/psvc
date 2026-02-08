#!/usr/bin/env python3
"""Quick import test to verify refactored modules load correctly"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

print("Testing imports...")

try:
    from psvc import Service
    print("✓ psvc.Service")
except ImportError as e:
    print(f"✗ psvc.Service: {e}")
    sys.exit(1)

try:
    from psvc.manage import TaskManager, parse_args, service_install, service_uninstall
    print("✓ psvc.manage (TaskManager, parse_args, service_install, service_uninstall)")
except ImportError as e:
    print(f"✗ psvc.manage: {e}")
    sys.exit(1)

try:
    from psvc.release import Releaser, ReleaseManager
    print("✓ psvc.release (Releaser, ReleaseManager)")
except ImportError as e:
    print(f"✗ psvc.release: {e}")
    sys.exit(1)

try:
    from psvc.update import Updater
    print("✓ psvc.update (Updater)")
except ImportError as e:
    print(f"✗ psvc.update: {e}")
    sys.exit(1)

try:
    from psvc.cmd import Commander, command
    print("✓ psvc.cmd (Commander, command)")
except ImportError as e:
    print(f"✗ psvc.cmd: {e}")
    sys.exit(1)

try:
    from psvc.network import Socket
    print("✓ psvc.network (Socket)")
except ImportError as e:
    print(f"✗ psvc.network: {e}")
    sys.exit(1)

print("\n✓ All imports successful!")
print("\nVerifying __init__.py exports...")

import psvc
expected = ['Service', 'Commander', 'command', 'Socket', 'Releaser', 'Updater', 'ReleaseManager']
for name in expected:
    if hasattr(psvc, name):
        print(f"✓ psvc.{name}")
    else:
        print(f"✗ psvc.{name} not exported")
        sys.exit(1)

print("\n✓ All exports verified!")
