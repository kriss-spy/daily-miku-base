import sys
import os
from pathlib import Path

# Add current directory to path
sys.path.append(os.getcwd())

try:
    import api.index
    print("Successfully imported api.index")
except Exception as e:
    print(f"Failed to import api.index: {e}")
    import traceback
    traceback.print_exc()
