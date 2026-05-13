# SimpliSQL - DuckDB SQL Query Editor

A feature-rich, professional SQL query editor powered by **DuckDB** with AI assistance, workflow automation, and advanced data management capabilities.

![Python](https://img.shields.io/badge/Python-3.9+-blue)
![PyQt6](https://img.shields.io/badge/PyQt6-Latest-green)
![DuckDB](https://img.shields.io/badge/DuckDB-Latest-orange)
![License](https://img.shields.io/badge/License-MIT-blue)

## ✨ Features

### Core Functionality
- **SQL Query Editor** - Syntax highlighting, autocomplete, validation
- **Multi-Format Support** - CSV, Excel, XML, JSON, ZIP archives
- **Data Visualization** - Line charts, bar charts, scatter plots with advanced controls
- **Query Management** - Save, load, and organize frequently-used queries
- **Export Capabilities** - Export to CSV, Excel, Parquet with filtered views support

### Advanced Features
- **Workflow Automation** - Create multi-step data transformation pipelines
- **View Management** - Save custom data views with filtering and column selection
- **Audit Reports** - Generate PDF reports with query execution details
- **AI Assistant** - Local Gemma model integration via Ollama for SQL generation and optimization
- **Dark Theme** - Professional dark UI with customizable theme support

### AI Integration
- **Local Gemma Model** - Privacy-focused AI via Ollama (no cloud dependencies)
- **Chat Interface** - Real-time SQL assistance and query optimization
- **Chat History** - Persistent conversation history for reference

## 📋 Requirements

### System Requirements
- **Python**: 3.9 or higher
- **RAM**: 4GB minimum (8GB recommended)
- **OS**: Windows, macOS, Linux
- **Ollama**: Required for local AI (optional, but recommended)

### Python Dependencies
```
duckdb>=0.8.0
pandas>=1.3.0
PyQt6>=6.0.0
pyperclip>=1.8.0
reportlab>=3.6.0
matplotlib>=3.5.0
plotly>=5.0.0
anthropic>=0.3.0  # Optional: for cloud AI
openai>=0.27.0    # Optional: for cloud AI
google-generativeai>=0.1.0  # Optional: for cloud AI
```

## 🚀 Installation

### Option 1: Executable (Windows)
Download the latest `SimpliSQL.exe` from [Releases](https://github.com/your-repo/releases) and run directly. No installation needed.

### Option 2: From Source

#### Prerequisites
1. **Install Python 3.9+** from [python.org](https://www.python.org)
2. **Install Ollama** from [ollama.ai](https://ollama.ai) (for local AI features)

#### Steps

```bash
# Clone the repository
git clone https://github.com/your-repo/simplisql.git
cd simplisql

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run application
python Simplisql.py
```

## 🎯 Quick Start

### 1. Launch the Application
```bash
python Simplisql.py
```

### 2. Load Data
- Click **"📥 Upload Files"** button
- Select CSV, Excel, or other supported formats
- Configure import settings (delimiter, sheet selection, etc.)
- Click **"Import"**

### 3. Write a Query
```sql
SELECT 
    DATE_TRUNC('month', transaction_date) as month,
    COUNT(*) as transaction_count,
    SUM(amount) as total_amount
FROM transactions
GROUP BY DATE_TRUNC('month', transaction_date)
ORDER BY month DESC
```

### 4. Execute & Visualize
- Press **Ctrl+Enter** or click **"🚀 Run Query"**
- View results in the results table
- Use **"📊 View Data"** for advanced filtering
- Create charts via **"📈 Data Visualization"**

### 5. Create Automated Workflows
- Click **"⚙️ Workflows"** → **"Create Workflow"**
- Add transformation steps (Filter, Group, Join, etc.)
- Save and execute with row-limit for testing
- Schedule workflows for batch processing

## 🔧 Configuration

### AI Configuration

#### Local AI (Ollama/Gemma) - Recommended
1. **Install Ollama**: Download from [ollama.ai](https://ollama.ai)
2. **Pull Gemma Model**:
   ```bash
   ollama pull gemma:2b  # Fast, 2B parameters
   # or
   ollama pull gemma:7b  # Better quality, 7B parameters
   ```
3. **Start Ollama Service**:
   ```bash
   ollama serve
   ```
4. **Configure in SimpliSQL**:
   - Open AI Assistant dialog (🤖 icon)
   - Ollama will auto-detect local service
   - Select Gemma model from provider dropdown

#### Cloud AI (Optional)
For cloud AI providers, set API keys in the AI Assistant dialog:
- **OpenAI**: Get from [platform.openai.com](https://platform.openai.com/api-keys)
- **Anthropic**: Get from [console.anthropic.com](https://console.anthropic.com)
- **Google Gemini**: Get from [makersuite.google.com](https://makersuite.google.com)

### Theme Configuration
Themes are auto-saved. Access theme selector in the action bar.

## 📚 Documentation

### [Architecture Guide](docs/ARCHITECTURE.md)
Detailed explanation of module structure, design patterns, and data flow.

### [API Reference](docs/API.md)
Complete API documentation for all modules and methods.

### [Data Visualization Guide](ui/LINE_CHART_USAGE.md)
In-depth guide to creating and customizing charts.

### [Custom SQL Functions](docs/CUSTOM_FUNCTIONS.md)
Reference for available custom SQL functions:
- `FILE_BASENAME(path)` - Extract filename
- `FILE_DIRNAME(path)` - Extract directory
- `FILE_NAME_NO_EXT(path)` - Filename without extension
- `FILE_EXTENSION(path)` - Extract file extension

## 🧪 Testing

Run the test suite to verify functionality:

```bash
# Install test dependencies
pip install pytest pytest-cov

# Run all tests
pytest tests/ -v

# Run with coverage report
pytest tests/ --cov=simplsql_modules --cov-report=html
```

Test results are saved to `htmlcov/index.html`.

## 📦 Building Executable

### Prerequisites
```bash
pip install pyinstaller
```

### Build Steps
```bash
# Standard build
pyinstaller SimpliSQL.spec

# Or build from scratch
pyinstaller --onefile \
  --windowed \
  --icon=sql.ico \
  --name=SimpliSQL \
  --add-data "sql.png:." \
  --add-data "sql.ico:." \
  Simplisql.py
```

The executable will be in the `dist/` folder.

## 🏗️ Architecture Overview

```
SimpliSQL/
├── Simplisql.py              # Main application & UI
├── simplsql_modules/
│   ├── core/                 # Query execution, file handling
│   │   ├── query_manager.py
│   │   ├── file_upload.py
│   │   ├── file_utilities.py
│   │   ├── workflow_manager.py
│   │   └── export_utils.py
│   ├── ui/                   # UI components & dialogs
│   │   ├── ui_builder.py
│   │   ├── view_manager.py
│   │   ├── dialogs.py
│   │   └── widgets.py
│   ├── ai/                   # AI integration
│   │   └── ai_assistant.py
│   └── utils/                # Utilities & helpers
│       ├── paths.py
│       ├── threads.py
│       └── models.py
├── tests/                    # Test suite (pytest)
├── Auto_Workflow/            # Configuration storage
├── ParquetFiles/             # Uploaded data storage
└── requirements.txt
```

## 🔒 Privacy & Security

- **Local AI**: Gemma model runs locally on your machine (no data sent to cloud)
- **No Tracking**: No telemetry or usage tracking
- **Data Storage**: All data stored locally in ParquetFiles directory
- **Configuration**: API keys stored locally in encrypted JSON files (optional)

## 🐛 Troubleshooting

### Ollama Not Connecting
```bash
# Check if Ollama service is running
curl http://localhost:11434/api/tags

# Restart Ollama service
ollama serve
```

### Data Import Fails
- Ensure file format matches selected type (CSV, Excel, etc.)
- Check for special characters in file paths
- Verify column headers are present

### Large Dataset Performance
- Use row limits for testing queries first
- Enable sorting with caution on large tables
- Consider pre-filtering data before import

### Chart Generation Issues
- Ensure X and Y columns are selected and contain valid data
- Check for NULL values in visualization columns
- Try a simpler chart type first

## 🤝 Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see [LICENSE](LICENSE) file for details.

## 🙋 Support

- **Issues**: Report bugs via [GitHub Issues](https://github.com/your-repo/issues)
- **Documentation**: Check [docs/](docs/) folder for detailed guides
- **Examples**: See [examples/](examples/) for sample workflows

## 🎨 Features Roadmap

- [ ] Remote database connectivity (PostgreSQL, MySQL, etc.)
- [ ] Scheduled workflow execution
- [ ] Query performance profiling
- [ ] Advanced SQL formatting and refactoring
- [ ] Custom user-defined functions (UDFs)
- [ ] Data quality monitoring
- [ ] Collaborative editing

## 📝 Changelog

### Version 2.0 (Current)
- ✨ Local Gemma model integration via Ollama
- 🐛 Improved error handling and logging
- 📊 Enhanced visualization options
- ⚡ Performance optimizations
- 📚 Comprehensive test suite

### Version 1.0
- Initial release with core SQL functionality
- Cloud AI providers support
- Workflow automation

---

**Made with ❤️ for data professionals**
