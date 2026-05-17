#!/usr/bin/env python3
"""
Quick test script for the GUI application.

This script tests that all dependencies are installed and the GUI can launch.
No actual uploads are performed in this test.

Usage:
    python test_gui.py
"""

import sys
from pathlib import Path

def check_imports():
    """Check if all required modules are available."""
    modules = {
        "customtkinter": "CustomTkinter (GUI framework)",
        "huggingface_hub": "Hugging Face Hub API",
        "requests": "HTTP library",
        "tqdm": "Progress bars",
    }
    
    print("🔍 Checking required modules...\n")
    
    missing = []
    for module_name, description in modules.items():
        try:
            __import__(module_name)
            print(f"✅ {module_name:20} — {description}")
        except ImportError:
            print(f"❌ {module_name:20} — {description} [MISSING]")
            missing.append(module_name)
    
    if missing:
        print(f"\n⚠️  Missing modules: {', '.join(missing)}")
        print(f"\nInstall with:")
        print(f"  pip install {' '.join(missing)}")
        return False
    
    print(f"\n✅ All modules installed!")
    return True


def check_local_files():
    """Check if GUI files exist."""
    print("\n🔍 Checking local files...\n")
    
    files_to_check = [
        "upload_logic.py",
        "main_gui.py",
        "requirements_gui.txt",
    ]
    
    all_exist = True
    for filename in files_to_check:
        filepath = Path(__file__).parent / filename
        if filepath.exists():
            size_kb = filepath.stat().st_size / 1024
            print(f"✅ {filename:25} ({size_kb:.1f} KB)")
        else:
            print(f"❌ {filename:25} [NOT FOUND]")
            all_exist = False
    
    return all_exist


def test_gui_launch():
    """Attempt to launch the GUI."""
    print("\n🚀 Launching GUI...\n")
    
    try:
        from main_gui import HFUploaderApp
        
        print("✅ GUI imported successfully!")
        print("📋 Creating application window...")
        
        app = HFUploaderApp()
        
        print("✅ GUI window created successfully!")
        print("\n💡 Tips:")
        print("  • Fill in test values (repo ID, token, folder paths)")
        print("  • Click 'Start Upload' to trigger the upload logic")
        print("  • Watch for logs in the progress textbox")
        print("  • Close the window to exit")
        print("\nPress Ctrl+C to close the window from this terminal.\n")
        
        # Run the GUI
        app.mainloop()
        
        return True
        
    except Exception as e:
        print(f"❌ Failed to launch GUI: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all checks and optionally launch GUI."""
    print("=" * 60)
    print("HF Dataset Uploader — GUI Test Suite")
    print("=" * 60)
    
    # Step 1: Check imports
    if not check_imports():
        print("\n⚠️  Cannot proceed without missing modules.")
        print("Please install them and try again.")
        return 1
    
    # Step 2: Check files
    if not check_local_files():
        print("\n⚠️  Some GUI files are missing.")
        print("Ensure you're running this from the hf_bulk_upload_tool/ directory.")
        return 1
    
    # Step 3: Launch GUI
    print("\n" + "=" * 60)
    answer = input("Launch GUI? (yes/no): ").strip().lower()
    
    if answer in ['y', 'yes']:
        if not test_gui_launch():
            return 1
    else:
        print("\n✅ All checks passed! You can now run: python main_gui.py")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
