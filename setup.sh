#!/bin/bash

# Document Q&A System Setup Script

echo "🚀 Setting up Document Q&A System..."

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required"
    exit 1
fi

# Install Python dependencies
echo "📦 Installing Python dependencies..."
pip install -r requirements.txt

# Download spaCy model
echo "🧠 Downloading spaCy model..."
python -m spacy download en_core_web_sm

# Check PostgreSQL
if ! command -v psql &> /dev/null; then
    echo "❌ PostgreSQL is required. Please install:"
    echo "   sudo apt-get install postgresql postgresql-contrib"
    exit 1
fi

# Setup database
echo "🗄️ Setting up database..."
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/docqa"

# Create database if not exists
createdb docqa 2>/dev/null || echo "Database 'docqa' already exists"

# Apply schema
psql docqa < schema.sql

echo "✅ Setup complete!"
echo ""
echo "🏃 To start the server:"
echo "   export DATABASE_URL='postgresql://postgres:postgres@localhost:5432/docqa'"
echo "   python server.py"
echo ""
echo "🌐 Then open http://localhost:8000"