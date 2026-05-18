#!/usr/bin/env python3
"""
Quick start script for Document Q&A System
"""

import os
import sys
import subprocess
import asyncio
from pathlib import Path

def check_dependencies():
    """Check if required dependencies are available"""
    try:
        import asyncpg
        import redis
        import spacy
        import sentence_transformers
        import fastapi
        print("✅ All Python dependencies available")
        return True
    except ImportError as e:
        print(f"❌ Missing Python dependency: {e}")
        print("Run: pip install -r requirements.txt")
        return False

def check_databases():
    """Check if databases are accessible"""
    # Check PostgreSQL
    try:
        import asyncpg
        database_url = os.getenv('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/docqa')
        # This is a simple check - full connection test would be async
        print("✅ PostgreSQL configuration available")
    except Exception as e:
        print(f"⚠️  PostgreSQL check skipped: {e}")

    # Check Redis
    try:
        import redis
        redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
        r = redis.from_url(redis_url)
        r.ping()
        print("✅ Redis connection successful")
        return True
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")
        print("Start Redis with: redis-server")
        return False

def setup_environment():
    """Setup environment variables"""
    env_vars = {
        'DATABASE_URL': 'postgresql://postgres:postgres@localhost:5432/docqa',
        'REDIS_URL': 'redis://localhost:6379',
        'UPLOAD_DIR': '/tmp/documents'
    }

    for key, default_value in env_vars.items():
        if key not in os.environ:
            os.environ[key] = default_value
            print(f"🔧 Set {key}={default_value}")

def main():
    """Main startup script"""
    print("🚀 Starting Document Q&A System")
    print("=" * 50)

    # Change to script directory
    script_dir = Path(__file__).parent.absolute()
    os.chdir(script_dir)

    # Check dependencies
    if not check_dependencies():
        sys.exit(1)

    # Setup environment
    setup_environment()

    # Check databases
    if not check_databases():
        print("⚠️  Some database connections failed - system may not work properly")

    # Create upload directory
    upload_dir = os.getenv('UPLOAD_DIR', '/tmp/documents')
    Path(upload_dir).mkdir(parents=True, exist_ok=True)
    print(f"📁 Upload directory: {upload_dir}")

    # Start the server
    print("\n🌐 Starting FastAPI server...")
    print("📍 Access the web interface at: http://localhost:8000")
    print("📖 API documentation at: http://localhost:8000/docs")
    print("\nPress Ctrl+C to stop the server")
    print("=" * 50)

    try:
        # Add backend to Python path
        sys.path.insert(0, str(script_dir / 'backend'))

        # Start uvicorn server
        subprocess.run([
            sys.executable, '-m', 'uvicorn',
            'backend.api.main:app',
            '--host', '0.0.0.0',
            '--port', '8000',
            '--reload'
        ])
    except KeyboardInterrupt:
        print("\n👋 Shutting down server...")
    except Exception as e:
        print(f"❌ Server startup failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()