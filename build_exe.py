#!/usr/bin/env python3
"""
Build script for creating PyInstaller executable
"""

import subprocess
import sys
import os
import shutil
from pathlib import Path

def build_executable():
    """
    Build the executable using PyInstaller
    """
    print("🔨 Building Shopify-SAP Integration Executable...")
    print("=" * 60)
    
    # Check if PyInstaller is installed
    try:
        import PyInstaller
        print(f"✅ PyInstaller version: {PyInstaller.__version__}")
    except ImportError:
        print("❌ PyInstaller not found. Installing...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
    
    # Clean previous builds
    dist_dir = Path("dist")
    build_dir = Path("build")
    
    if dist_dir.exists():
        print("🧹 Cleaning previous dist directory...")
        shutil.rmtree(dist_dir)
    
    if build_dir.exists():
        print("🧹 Cleaning previous build directory...")
        shutil.rmtree(build_dir)
    
    # Build the executable
    print("🔨 Building executable...")
    result = subprocess.run([
        "pyinstaller",
        "--clean",
        "continuous_sync.spec"
    ], capture_output=True, text=True)
    
    if result.returncode == 0:
        print("✅ Build completed successfully!")
        
        # Check if executable was created
        exe_path = dist_dir / "ShopifySAPIntegration.exe"
        if exe_path.exists():
            print(f"📦 Executable created: {exe_path}")
            print(f"📁 Size: {exe_path.stat().st_size / (1024*1024):.1f} MB")
            
            # Create a batch file for easy execution with continuous mode
            batch_content = """@echo off
echo ========================================
echo Shopify-SAP Integration - Continuous Mode
echo ========================================
echo.
echo This will run all enabled sync processes continuously.
echo Each sync process will run on its own interval as configured.
echo.
echo Press Ctrl+C to stop all syncs gracefully.
echo.
pause
echo.
echo Starting continuous sync...
ShopifySAPIntegration.exe
echo.
echo Continuous sync stopped.
pause
"""
            batch_path = dist_dir / "run_continuous_sync.bat"
            with open(batch_path, 'w') as f:
                f.write(batch_content)
            
            print(f"📄 Batch file created: {batch_path}")
            
            # Copy configuration file to dist
            if Path("configurations.json").exists():
                shutil.copy2("configurations.json", dist_dir)
                print("📋 Configuration file copied to dist directory")
            
            # Copy color metaobject mappings file to dist
            import json
            if Path("color_metaobject_mappings.json").exists():
                shutil.copy2("color_metaobject_mappings.json", dist_dir)
                print("🎨 Color metaobject mappings file copied to dist directory")
            else:
                # Create empty file if it doesn't exist
                empty_mappings = {"local": {}, "international": {}}
                mappings_path = dist_dir / "color_metaobject_mappings.json"
                with open(mappings_path, 'w', encoding='utf-8') as f:
                    json.dump(empty_mappings, f, indent=4, ensure_ascii=False)
                print("🎨 Created empty color metaobject mappings file in dist directory")
            
            print("\n🎉 Build completed successfully!")
            print("📁 Output directory: dist/")
            print("🚀 To run: double-click run_continuous_sync.bat or ShopifySAPIntegration.exe")
            print("ℹ️  The executable will run in continuous mode by default")
            
        else:
            print("❌ Executable not found in dist directory")
            return False
    else:
        print("❌ Build failed!")
        print("Error output:")
        print(result.stderr)
        return False
    
    return True

if __name__ == "__main__":
    try:
        success = build_executable()
        if not success:
            sys.exit(1)
    except Exception as e:
        print(f"❌ Build script failed: {str(e)}")
        sys.exit(1) 