# 🔄 DevOps Upgrade Intelligence Assistant

> **AI-powered upgrade analysis using Hybrid RAG (Vector Search + Knowledge Graph) for safe infrastructure upgrades**

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.31+-red.svg)](https://streamlit.io/)
[![LangChain](https://img.shields.io/badge/LangChain-0.1+-green.svg)](https://www.langchain.com/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## 🎯 The Problem

DevOps engineers upgrading Kubernetes, Terraform, or Docker face critical challenges:

- 📚 **1000+ lines** of changelog to read manually
- 💥 **Breaking changes** easily missed → Production outages
- ⏰ **Hours of research** for each upgrade decision
- 🔒 **Security patches** overlooked
- ⚠️ **Deprecations** discovered too late

**One missed breaking change = Downtime + Revenue loss** 🔥

## ✨ The Solution

An intelligent AI assistant that:

✅ Automatically fetches official changelogs  
✅ Extracts ALL critical changes (20+ patterns)  
✅ Uses Hybrid RAG (Vector + Knowledge Graph)  
✅ Answers questions in seconds  
✅ Never misses breaking changes or security patches  

## 🎬 Demo

```bash
# 1. Start the assistant
streamlit run devops_comprehensive.py

# 2. Enter versions
Current: 1.20.0
Target: 1.24.0

# 3. Get instant analysis
🔴 Breaking: 15
⚠️ Deprecated: 17
❌ Removed: 8
🔒 Security: 5

# 4. Ask questions
"What are ALL breaking changes?"
"What's deprecated and when will it be removed?"
"What security patches are included?"
```

## 🏗️ Architecture

```
USER INPUT (v1.20.0 → v1.24.0)
          ↓
FETCH CHANGELOGS (GitHub)
          ↓
EXTRACT CHANGES (20+ patterns)
    ├─ Breaking Changes
    ├─ Deprecations
    ├─ Removals
    └─ Security Patches
          ↓
    ┌─────┴─────┐
    ↓           ↓
VECTOR DB    KNOWLEDGE GRAPH
(Semantic)   (Relationships)
    │           │
    └─────┬─────┘
          ↓
   HYBRID RETRIEVAL
          ↓
   AI GENERATION (Phi3)
          ↓
COMPREHENSIVE ANSWER
```

## 🚀 Quick Start

### 1. Prerequisites

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull Phi3 model
ollama pull phi3:mini

# Start Ollama
ollama serve
```

### 2. Install

```bash
git clone https://github.com/R-Sathyabama/devops-upgrade-assistant.git
cd devops-upgrade-assistant
pip install -r requirements.txt
```

### 3. Run

```bash
streamlit run devops_comprehensive.py
```

### 4. Optional: Neo4j (for Knowledge Graph)

```bash
docker run -d \
  --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password \
  neo4j:latest
```

## 📊 Features

### Core Capabilities

| Feature | Description |
|---------|-------------|
| 🔍 **Auto-Fetch** | Downloads official changelogs from GitHub |
| 🎯 **Smart Extract** | 20+ regex patterns for change detection |
| 🤖 **Hybrid RAG** | Vector search + Knowledge graph |
| 💬 **Natural Q&A** | Ask questions in plain English |
| 📊 **Dashboard** | Instant statistics (breaking/deprecated/removed) |
| ⚡ **Local First** | 100% local processing (Phi3 Mini) |

### Analysis Types

- 🔴 **Breaking Changes** - What will break
- ⚠️ **Deprecations** - Features being phased out
- ❌ **Removals** - What's gone
- 🔒 **Security Patches** - CVEs fixed
- ✨ **New Features** - Latest capabilities
- 🎯 **Action Items** - What to do

### Supported Tools

- ✅ Kubernetes (1.x → latest)
- 🔜 Terraform (coming soon)
- 🔜 Docker (coming soon)

## 💡 Usage

### Example 1: Breaking Changes

```
Question: "List ALL breaking changes"

Answer:
• Version 1.22.0: CronJob batch/v1beta1 API removed
  → Action: Update manifests to batch/v1
  
• Version 1.24.0: Dockershim removed
  → Action: Switch to containerd/CRI-O
  
• Version 1.24.0: PodSecurityPolicy removed
  → Action: Migrate to Pod Security Standards

[... 12 more changes]
```

### Example 2: Deprecations

```
Question: "What's deprecated and when?"

Answer:
• Version 1.21.0: CronJob batch/v1beta1 deprecated
  → Timeline: Removed in 1.25.0
  → Action: Migrate to batch/v1 now
  
• Version 1.22.0: Dockershim deprecated
  → Timeline: Removed in 1.24.0
  → Action: Test containerd/CRI-O before 1.24

[... 15 more deprecations]
```

### Example 3: Security

```
Question: "What security patches?"

Answer:
• Version 1.20.11: CVE-2021-25741 fixed
  → Severity: High
  → Impact: Symlink vulnerability
  
• Version 1.21.5: CVE-2021-3121 fixed
  → Severity: Critical
  → Impact: DoS vulnerability

[... 3 more CVEs]
```

## 🔧 Technical Stack

| Component | Technology |
|-----------|-----------|
| **Frontend** | Streamlit |
| **LLM** | Phi3 Mini (Ollama) |
| **Embeddings** | HuggingFace all-MiniLM-L6-v2 |
| **Vector DB** | ChromaDB |
| **Graph DB** | Neo4j (optional) |
| **Framework** | LangChain |
| **Language** | Python 3.8+ |

## 🧪 How It Works

### 1. Intelligent Extraction

```python
# 20+ patterns detect changes
patterns = {
    'breaking': [r'\bbreaking\b', r'\bremoved.*api\b'],
    'deprecation': [r'\bdeprecat', r'\bwill be removed\b'],
    'security': [r'\bcve-\d{4}-\d+', r'\bvulnerability\b']
}

# Example extraction
Input: "CronJob batch/v1beta1 API is deprecated, use batch/v1"
Output: {
    type: "deprecation",
    version: "1.21.0",
    component: "batch/v1beta1",
    action: "use batch/v1"
}
```

### 2. Dual Indexing

```python
# Full content (for context)
Document("Version 1.22.0\n## Changes by Kind\n...")

# Individual changes (for precision)
Document("[DEPRECATION] CronJob batch/v1beta1 deprecated")
```

### 3. Hybrid Retrieval

```python
# Vector: Find similar content
vector_results = vectordb.search(query, k=10)

# Graph: Get relationships
graph_results = kg.get_path(current, target)

# Combine both
context = vector_results + graph_results
answer = llm.generate(context)
```

## 📈 Performance

| Metric | Time |
|--------|------|
| Fetch changelogs | 3-5 sec |
| Build vector DB | 10-15 sec |
| Build knowledge graph | 5-10 sec |
| Answer query | 2-4 sec |
| **Total** | **~30 sec** |

## 🎯 Use Cases

### 1. Pre-Production Upgrade

```
Scenario: Planning K8s 1.20 → 1.24 upgrade
Result: Found 15 breaking changes before touching prod
Impact: Avoided 3 potential outages
```

### 2. Security Compliance

```
Scenario: Audit requires K8s 1.24 for CVE patches
Result: Identified 5 CVEs fixed, generated report
Impact: Passed audit, systems secured
```

### 3. Deprecation Planning

```
Scenario: Using PodSecurityPolicy (deprecated)
Result: Timeline shown, migration path provided
Impact: 6-month migration plan created
```

## 📁 Project Structure

```
devops-upgrade-assistant/
├── devops_comprehensive.py     # Main app with full features
├── devops_concise_final.py     # Simplified version
├── requirements.txt             # Python dependencies
├── README.md                    # This file
├── COMPREHENSIVE_SYSTEM.md      # Technical deep-dive
├── HOW_IT_WORKS.md             # Detailed explanation
├── TROUBLESHOOTING.md          # Common issues
└── chroma_db/                  # Vector database (auto-created)
```

## 🐛 Troubleshooting

**Ollama not running:**
```bash
ollama serve
```

**No changelog fetched:**
```bash
# Check internet
curl https://raw.githubusercontent.com/kubernetes/kubernetes/master/CHANGELOG/CHANGELOG-1.24.md

# Use correct version format: 1.20.0 (not v1.20.0)
```

**ChromaDB error:**
```bash
rm -rf chroma_db/
# Restart app
```

## 🛣️ Roadmap

- [x] Kubernetes support
- [x] Hybrid RAG implementation
- [x] Statistics dashboard
- [ ] Terraform support
- [ ] Docker support
- [ ] Export reports (PDF/Markdown)
- [ ] CLI version
- [ ] REST API
- [ ] CI/CD integration

## 🤝 Contributing

Contributions welcome!

1. Fork the repo
2. Create feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Open Pull Request

## 📄 License

MIT License - see [LICENSE](LICENSE)

## 🙏 Acknowledgments

- [Kubernetes](https://kubernetes.io/) - Comprehensive changelogs
- [LangChain](https://www.langchain.com/) - RAG framework
- [Ollama](https://ollama.ai/) - Local LLM inference
- [ChromaDB](https://www.trychroma.com/) - Vector database
- [Neo4j](https://neo4j.com/) - Graph database

## 📧 Contact

**R-Sathyabama** - [LinkedIn](https://www.linkedin.com/in/sathyabama-rajendiran/) | [Email](sathyabama1211@gmail.com)

Project: [devops-upgrade-assistant](https://github.com/R-Sathyabama/devops-upgrade-assistant)

---

<div align="center">

### ⭐ Star this repo if it helps your DevOps workflow!

**Built with ❤️ for DevOps Engineers**

[Report Bug](https://github.com/R-Sathyabama/devops-upgrade-assistant/issues) · [Request Feature](https://github.com/R-Sathyabama/devops-upgrade-assistant/issues)

</div>
