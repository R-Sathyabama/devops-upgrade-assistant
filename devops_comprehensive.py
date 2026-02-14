"""
Complete DevOps Upgrade Assistant with Hybrid RAG
- Extracts ALL critical information: breaking changes, deprecations, removals, security patches
- Uses both Vector Search (semantic) and Knowledge Graph (relationships)
- Never misses important upgrade details
- Provides comprehensive analysis for safe upgrades
"""

import streamlit as st
import requests
import re
import os
import shutil
from typing import List, Dict, Tuple, Set
from dataclasses import dataclass
from enum import Enum

from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.chat_models import ChatOllama
from langchain.prompts import PromptTemplate
from langchain.docstore.document import Document
from langchain.chains import LLMChain
from neo4j import GraphDatabase
from chromadb.config import Settings

# -------------------------------------------------
# Data Models
# -------------------------------------------------
class ChangeType(Enum):
    BREAKING = "breaking"
    DEPRECATION = "deprecation"
    REMOVAL = "removal"
    SECURITY = "security"
    FEATURE = "feature"
    BUG_FIX = "bug_fix"
    BEHAVIOR = "behavior_change"

@dataclass
class Change:
    version: str
    type: ChangeType
    description: str
    component: str = ""
    action_required: str = ""

@dataclass
class VersionInfo:
    version: str
    changes: List[Change]
    raw_content: str

# -------------------------------------------------
# Page Config
# -------------------------------------------------
st.set_page_config(
    page_title="DevOps Upgrade Intelligence", 
    layout="wide",
    page_icon="🔄"
)

st.title("🔄 DevOps Upgrade Intelligence Assistant")
st.markdown("*Comprehensive upgrade analysis with Hybrid RAG - Never miss critical changes*")

# -------------------------------------------------
# Session State
# -------------------------------------------------
def init_session_state():
    defaults = {
        'vectordb': None,
        'kg': None,
        'version_data': {},
        'current_version': '',
        'target_version': '',
        'tool_name': 'Kubernetes',
        'ready': False,
        'all_changes': [],
        'analysis_complete': False
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# -------------------------------------------------
# Sidebar
# -------------------------------------------------
with st.sidebar:
    st.header("⚙️ Configuration")
    
    tool = st.selectbox("🛠️ Tool", ["Kubernetes", "Terraform", "Docker"], key="tool")
    current = st.text_input("📌 Current", placeholder="1.20.0", key="curr")
    target = st.text_input("🎯 Target", placeholder="1.24.0", key="targ")
    
    st.markdown("---")
    st.markdown("### 🔍 Analysis Scope")
    analyze_breaking = st.checkbox("🔴 Breaking Changes", value=True)
    analyze_deprecations = st.checkbox("⚠️ Deprecations", value=True)
    analyze_removals = st.checkbox("❌ Removals", value=True)
    analyze_security = st.checkbox("🔒 Security Patches", value=True)
    analyze_features = st.checkbox("✨ New Features", value=True)
    
    st.markdown("---")
    
    # Neo4j settings
    with st.expander("🗄️ Neo4j (Optional)"):
        neo4j_enabled = st.checkbox("Enable Neo4j KG")
        neo4j_uri = st.text_input("URI", "bolt://localhost:7687")
        neo4j_user = st.text_input("User", "neo4j")
        neo4j_pass = st.text_input("Password", "password", type="password")
    
    debug = st.checkbox("🔍 Debug", key="debug")
    
    if st.button("🗑️ Reset All"):
        if os.path.exists("./chroma_db"):
            shutil.rmtree("./chroma_db")
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

# -------------------------------------------------
# Helper Functions
# -------------------------------------------------
def normalize_version(v: str) -> str:
    v = v.strip()
    return v[1:] if v.startswith('v') else v

def fetch_k8s_changelog(version: str) -> Tuple[str, str]:
    parts = version.split('.')
    if len(parts) >= 2:
        major_minor = f"{parts[0]}.{parts[1]}"
        url = f"https://raw.githubusercontent.com/kubernetes/kubernetes/master/CHANGELOG/CHANGELOG-{major_minor}.md"
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                return resp.text, url
        except:
            pass
    return None, None

def extract_changes_from_content(content: str, version: str) -> List[Change]:
    """Extract all types of changes from changelog content"""
    changes = []
    lines = content.split('\n')
    
    # Patterns for different change types
    patterns = {
        ChangeType.BREAKING: [
            r'(?i)\bbreaking\b.*?change',
            r'(?i)\bremoved?.*?(api|feature|support)',
            r'(?i)\bmust\b.*?(update|change|migrate)',
            r'(?i)\bno longer\b',
        ],
        ChangeType.DEPRECATION: [
            r'(?i)\bdeprecat(ed|ion|ing)\b',
            r'(?i)\bwill be removed\b',
            r'(?i)\blegacy\b',
        ],
        ChangeType.REMOVAL: [
            r'(?i)\bremoved?\b',
            r'(?i)\bdeleted?\b',
            r'(?i)\bdropped?\b',
        ],
        ChangeType.SECURITY: [
            r'(?i)\bsecurity\b',
            r'(?i)\bcve-\d{4}-\d+',
            r'(?i)\bvulnerability\b',
            r'(?i)\bpatch(es|ed)?\b.*?security',
        ],
        ChangeType.FEATURE: [
            r'(?i)\bnew feature\b',
            r'(?i)\badded?\b',
            r'(?i)\bintroduced?\b',
            r'(?i)\bga\b',  # General Availability
        ]
    }
    
    for i, line in enumerate(lines):
        line_lower = line.lower()
        
        # Skip empty or header lines
        if not line.strip() or line.startswith('#'):
            continue
        
        # Check each pattern
        for change_type, pattern_list in patterns.items():
            for pattern in pattern_list:
                if re.search(pattern, line_lower):
                    # Extract component (API name, feature name, etc.)
                    component = extract_component(line)
                    
                    # Get context (surrounding lines)
                    context_lines = lines[max(0, i-1):min(len(lines), i+3)]
                    description = '\n'.join(context_lines).strip()
                    
                    changes.append(Change(
                        version=version,
                        type=change_type,
                        description=line.strip(),
                        component=component
                    ))
                    break
    
    return changes

def extract_component(text: str) -> str:
    """Extract component/API/feature name from text"""
    # Match patterns like: APIName, feature-name, api/version
    patterns = [
        r'\b([A-Z][a-zA-Z]+(?:API|Policy|Controller|Manager))\b',
        r'\b(batch/v\w+|apps/v\w+|core/v\w+)\b',
        r'\b([a-z]+-[a-z]+)\b',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return ""

def parse_k8s_changelog(content: str) -> List[VersionInfo]:
    """Parse Kubernetes changelog with detailed extraction"""
    if not content:
        return []
    
    versions = []
    lines = content.split('\n')
    current_version = None
    current_content = []
    
    for line in lines:
        # Version header
        match = re.match(r'^#{1,2}\s+v?(\d+\.\d+\.\d+)', line)
        if match:
            # Save previous
            if current_version and current_content:
                text = '\n'.join(current_content)
                if len(text.strip()) > 100:
                    changes = extract_changes_from_content(text, current_version)
                    versions.append(VersionInfo(
                        version=current_version,
                        changes=changes,
                        raw_content=text
                    ))
            
            current_version = match.group(1)
            current_content = [line]
        else:
            if current_version:
                current_content.append(line)
    
    # Last version
    if current_version and current_content:
        text = '\n'.join(current_content)
        if len(text.strip()) > 100:
            changes = extract_changes_from_content(text, current_version)
            versions.append(VersionInfo(
                version=current_version,
                changes=changes,
                raw_content=text
            ))
    
    return versions

def filter_versions(versions: List[VersionInfo], start: str, end: str) -> List[VersionInfo]:
    def to_tuple(v):
        try:
            return tuple(map(int, v.split('.')))
        except:
            return (0, 0, 0)
    
    start_t = to_tuple(start)
    end_t = to_tuple(end)
    
    return [v for v in versions if start_t <= to_tuple(v.version) <= end_t]

# -------------------------------------------------
# Knowledge Graph (Neo4j)
# -------------------------------------------------
class UpgradeKnowledgeGraph:
    def __init__(self, uri, user, password):
        self.connected = False
        try:
            self.driver = GraphDatabase.driver(uri, auth=(user, password))
            with self.driver.session() as session:
                session.run("RETURN 1")
            self.connected = True
        except:
            self.driver = None
    
    def create_upgrade_graph(self, tool: str, versions: List[VersionInfo]):
        if not self.connected:
            return
        
        with self.driver.session() as session:
            # Clear old data
            session.run("MATCH (n) DETACH DELETE n")
            
            # Create tool node
            session.run("MERGE (t:Tool {name: $tool})", tool=tool)
            
            # Create version nodes with metadata
            for v_info in versions:
                has_breaking = any(c.type == ChangeType.BREAKING for c in v_info.changes)
                has_deprecated = any(c.type == ChangeType.DEPRECATION for c in v_info.changes)
                has_removed = any(c.type == ChangeType.REMOVAL for c in v_info.changes)
                has_security = any(c.type == ChangeType.SECURITY for c in v_info.changes)
                
                session.run("""
                    MERGE (v:Version {name: $version, tool: $tool})
                    SET v.has_breaking = $breaking,
                        v.has_deprecations = $deprecated,
                        v.has_removals = $removed,
                        v.has_security = $security,
                        v.num_changes = $num_changes
                    """, 
                    version=v_info.version, tool=tool,
                    breaking=has_breaking, deprecated=has_deprecated,
                    removed=has_removed, security=has_security,
                    num_changes=len(v_info.changes)
                )
                
                # Link to tool
                session.run("""
                    MATCH (t:Tool {name: $tool})
                    MATCH (v:Version {name: $version, tool: $tool})
                    MERGE (t)-[:HAS_VERSION]->(v)
                    """, tool=tool, version=v_info.version)
                
                # Create change nodes
                for change in v_info.changes:
                    session.run("""
                        MERGE (c:Change {
                            description: $desc,
                            type: $type,
                            version: $version,
                            component: $component
                        })
                        WITH c
                        MATCH (v:Version {name: $version, tool: $tool})
                        MERGE (v)-[:HAS_CHANGE]->(c)
                        """,
                        desc=change.description[:200],
                        type=change.type.value,
                        version=v_info.version,
                        component=change.component,
                        tool=tool
                    )
            
            # Create version sequence
            sorted_versions = sorted(versions, key=lambda v: tuple(map(int, v.version.split('.'))))
            for i in range(len(sorted_versions) - 1):
                session.run("""
                    MATCH (v1:Version {name: $v1, tool: $tool})
                    MATCH (v2:Version {name: $v2, tool: $tool})
                    MERGE (v1)-[:PRECEDES]->(v2)
                    """,
                    v1=sorted_versions[i].version,
                    v2=sorted_versions[i+1].version,
                    tool=tool
                )
    
    def get_upgrade_path_analysis(self, current: str, target: str, tool: str) -> Dict:
        if not self.connected:
            return {}
        
        with self.driver.session() as session:
            result = session.run("""
                MATCH path = (v1:Version {name: $current, tool: $tool})
                             -[:PRECEDES*]->(v2:Version {name: $target, tool: $tool})
                WITH path, nodes(path) as versions
                UNWIND versions as v
                OPTIONAL MATCH (v)-[:HAS_CHANGE]->(c:Change)
                RETURN 
                    v.name as version,
                    v.has_breaking as has_breaking,
                    v.has_security as has_security,
                    collect({type: c.type, desc: c.description, component: c.component}) as changes
                ORDER BY v.name
                """, current=current, target=target, tool=tool)
            
            path_data = []
            for record in result:
                path_data.append({
                    'version': record['version'],
                    'has_breaking': record['has_breaking'],
                    'has_security': record['has_security'],
                    'changes': record['changes']
                })
            
            return {'path': path_data}
    
    def close(self):
        if self.driver:
            self.driver.close()

# -------------------------------------------------
# Initialize Models
# -------------------------------------------------
@st.cache_resource
def get_embeddings():
    return HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        model_kwargs={'device': 'cpu'}
    )

@st.cache_resource
def get_llm():
    try:
        llm = ChatOllama(model="phi3:mini", temperature=0)
        llm.invoke("test")
        return llm, True
    except:
        return None, False

embeddings = get_embeddings()
llm, ollama_ok = get_llm()

if not ollama_ok:
    st.error("❌ Ollama not running! Start: `ollama serve`")
    st.stop()

# Initialize KG if enabled
kg = None
if neo4j_enabled:
    kg = UpgradeKnowledgeGraph(neo4j_uri, neo4j_user, neo4j_pass)
    if kg.connected:
        st.sidebar.success("✅ Neo4j Connected")
    else:
        st.sidebar.warning("⚠️ Neo4j connection failed")

# -------------------------------------------------
# Analysis Prompts
# -------------------------------------------------
COMPREHENSIVE_ANALYSIS_PROMPT = PromptTemplate(
    template="""You are a senior DevOps engineer analyzing upgrade documentation.

CHANGELOG CONTENT:
{context}

KNOWLEDGE GRAPH DATA:
{kg_data}

VERSION RANGE: {current_version} → {target_version}

QUESTION: {question}

INSTRUCTIONS:
1. Analyze BOTH the changelog text AND knowledge graph data
2. List ALL relevant changes with specific version numbers
3. Include exact API names, feature names, components affected
4. If it's a breaking change, deprecation, or removal - ALWAYS mention it
5. Provide specific action items for DevOps engineers
6. Never say "not mentioned" if the information exists in the context
7. Be comprehensive - missing critical info can cause production issues

ANSWER FORMAT:
- Start with summary
- List changes by version
- Highlight critical items (BREAKING, SECURITY)
- End with action items

Answer:""",
    input_variables=["context", "kg_data", "current_version", "target_version", "question"]
)

# -------------------------------------------------
# Main Analysis Function
# -------------------------------------------------
def comprehensive_analysis(tool: str, current: str, target: str):
    """Comprehensive upgrade analysis with hybrid RAG"""
    
    st.markdown("---")
    st.subheader(f"📊 Comprehensive Analysis: {tool}")
    
    current = normalize_version(current)
    target = normalize_version(target)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("From", current)
    with col2:
        st.metric("To", target)
    with col3:
        st.metric("Method", "Hybrid RAG" if kg and kg.connected else "Vector Only")
    
    # Fetch changelogs
    with st.spinner("🌐 Fetching changelogs..."):
        all_versions = []
        
        if tool == "Kubernetes":
            content1, _ = fetch_k8s_changelog(current)
            if content1:
                st.success(f"✅ Fetched {current} changelog")
                versions1 = parse_k8s_changelog(content1)
                all_versions.extend(versions1)
            
            content2, _ = fetch_k8s_changelog(target)
            if content2 and content2 != content1:
                st.success(f"✅ Fetched {target} changelog")
                versions2 = parse_k8s_changelog(content2)
                all_versions.extend(versions2)
    
    if not all_versions:
        st.error("❌ Failed to fetch changelog data")
        return None, []
    
    # Remove duplicates
    seen = set()
    unique_versions = []
    for v in all_versions:
        if v.version not in seen:
            seen.add(v.version)
            unique_versions.append(v)
    
    # Filter to range
    filtered = filter_versions(unique_versions, current, target)
    if not filtered:
        filtered = unique_versions[:15]
    
    st.info(f"📝 Analyzing {len(filtered)} versions")
    
    # Extract all changes
    all_changes = []
    for v_info in filtered:
        all_changes.extend(v_info.changes)
    
    # Show statistics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        breaking_count = sum(1 for c in all_changes if c.type == ChangeType.BREAKING)
        st.metric("🔴 Breaking", breaking_count)
    with col2:
        deprecated_count = sum(1 for c in all_changes if c.type == ChangeType.DEPRECATION)
        st.metric("⚠️ Deprecated", deprecated_count)
    with col3:
        removed_count = sum(1 for c in all_changes if c.type == ChangeType.REMOVAL)
        st.metric("❌ Removed", removed_count)
    with col4:
        security_count = sum(1 for c in all_changes if c.type == ChangeType.SECURITY)
        st.metric("🔒 Security", security_count)
    
    if debug:
        with st.expander("📊 Detailed Change Breakdown"):
            for v_info in filtered[:5]:
                st.markdown(f"**Version {v_info.version}:** {len(v_info.changes)} changes")
                for change in v_info.changes[:3]:
                    st.text(f"  [{change.type.value}] {change.description[:100]}")
    
    # Build Knowledge Graph
    if kg and kg.connected:
        with st.spinner("🕸️ Building Knowledge Graph..."):
            kg.create_upgrade_graph(tool, filtered)
            st.success("✅ Knowledge Graph created")
    
    # Build Vector Database
    with st.spinner("🗄️ Building Vector Database..."):
        try:
            # Combine all content with rich metadata
            docs = []
            for v_info in filtered:
                # Main content
                docs.append(Document(
                    page_content=f"Version {v_info.version}\n\n{v_info.raw_content}",
                    metadata={"version": v_info.version, "type": "full_content"}
                ))
                
                # Individual changes as separate documents for better retrieval
                for change in v_info.changes:
                    docs.append(Document(
                        page_content=f"[{change.type.value.upper()}] Version {v_info.version}: {change.description}",
                        metadata={
                            "version": v_info.version,
                            "type": change.type.value,
                            "component": change.component
                        }
                    ))
            
            # Clear old DB
            db_path = "./chroma_db"
            if os.path.exists(db_path):
                shutil.rmtree(db_path)
            os.makedirs(db_path, exist_ok=True)
            
            # Create vector store
            settings = Settings(
                anonymized_telemetry=False,
                allow_reset=True,
                is_persistent=True
            )
            
            vectordb = Chroma.from_documents(
                documents=docs,
                embedding=embeddings,
                persist_directory=db_path,
                client_settings=settings,
                collection_name="upgrade_docs"
            )
            
            vectordb.persist()
            st.success(f"✅ Vector DB: {len(docs)} documents")
            
            return vectordb, filtered, all_changes
            
        except Exception as e:
            st.error(f"❌ Vector DB error: {str(e)}")
            if debug:
                import traceback
                st.code(traceback.format_exc())
            return None, filtered, all_changes

# -------------------------------------------------
# Query Function with Hybrid RAG
# -------------------------------------------------
def hybrid_rag_query(query: str, vectordb, current: str, target: str, tool: str):
    """Query using both vector search and knowledge graph"""
    
    if not vectordb:
        return "❌ Vector database not ready", []
    
    try:
        # 1. Vector Search - get relevant documents
        retriever = vectordb.as_retriever(
            search_kwargs={"k": 10}  # Get more documents for comprehensive answer
        )
        docs = retriever.get_relevant_documents(query)
        
        # Combine vector search results
        context = "\n\n".join([doc.page_content for doc in docs])
        
        # 2. Knowledge Graph Query (if available)
        kg_data = ""
        if kg and kg.connected:
            path_analysis = kg.get_upgrade_path_analysis(current, target, tool)
            if path_analysis and 'path' in path_analysis:
                kg_data = "KNOWLEDGE GRAPH ANALYSIS:\n"
                for version_data in path_analysis['path']:
                    kg_data += f"\nVersion {version_data['version']}:\n"
                    if version_data['has_breaking']:
                        kg_data += "  - Contains BREAKING changes\n"
                    if version_data['has_security']:
                        kg_data += "  - Contains SECURITY fixes\n"
                    for change in version_data['changes'][:5]:
                        if change['desc']:
                            kg_data += f"  - [{change['type']}] {change['desc'][:100]}\n"
        
        # 3. Generate comprehensive answer using LLM
        chain = LLMChain(llm=llm, prompt=COMPREHENSIVE_ANALYSIS_PROMPT)
        
        result = chain.run(
            context=context,
            kg_data=kg_data,
            current_version=current,
            target_version=target,
            question=query
        )
        
        return result, docs
        
    except Exception as e:
        import traceback
        return f"Error: {str(e)}\n\n{traceback.format_exc() if debug else ''}", []

# -------------------------------------------------
# UI - Analysis
# -------------------------------------------------
st.info("""
💡 **DevOps-Grade Upgrade Analysis:**
- Extracts ALL breaking changes, deprecations, removals
- Identifies security patches and critical updates
- Uses Hybrid RAG (Vector + Knowledge Graph)
- Provides comprehensive, never-miss-anything analysis
""")

if st.button("🚀 Start Comprehensive Analysis", type="primary", disabled=not current or not target):
    # Save to session
    st.session_state.current_version = normalize_version(current)
    st.session_state.target_version = normalize_version(target)
    st.session_state.tool_name = tool
    
    # Run analysis
    vectordb, versions, changes = comprehensive_analysis(tool, current, target)
    
    if vectordb:
        st.session_state.vectordb = vectordb
        st.session_state.version_data = versions
        st.session_state.all_changes = changes
        st.session_state.ready = True
        st.session_state.analysis_complete = True
        st.success("✅ Comprehensive analysis complete!")
        st.balloons()

# -------------------------------------------------
# UI - Questions
# -------------------------------------------------
if st.session_state.ready:
    st.markdown("---")
    st.subheader("💬 Ask Comprehensive Questions")
    
    st.caption(f"Analysis: {st.session_state.tool_name} | "
              f"{st.session_state.current_version} → {st.session_state.target_version}")
    
    # Preset comprehensive questions
    preset_questions = {
        "🔴 Breaking Changes": "List ALL breaking changes with version numbers, affected components, and required actions",
        "⚠️ Deprecations": "List ALL deprecated features, when they were deprecated, when they'll be removed, and migration paths",
        "❌ Removals": "List ALL removed features, what versions they were removed in, and alternatives",
        "🔒 Security": "List ALL security patches, CVEs fixed, and security-related changes",
        "📋 Complete Summary": "Provide a COMPLETE upgrade summary including ALL critical changes, deprecations, removals, and security patches",
        "🎯 Action Items": "List ALL action items required for this upgrade in priority order",
    }
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.markdown("#### Comprehensive Queries")
        selected_preset = st.selectbox("Select:", list(preset_questions.keys()))
        if st.button("Ask Comprehensive Question", key="ask_preset"):
            st.session_state.query = preset_questions[selected_preset]
    
    with col2:
        st.markdown("#### Custom Query")
        custom_q = st.text_area("Your question:", height=100)
        if st.button("Ask Custom", key="ask_custom"):
            if custom_q:
                st.session_state.query = custom_q
    
    # Display answer
    if 'query' in st.session_state and st.session_state.query:
        st.markdown("---")
        st.markdown(f"### ❓ {st.session_state.query}")
        
        with st.spinner("🔍 Comprehensive analysis in progress..."):
            answer, sources = hybrid_rag_query(
                st.session_state.query,
                st.session_state.vectordb,
                st.session_state.current_version,
                st.session_state.target_version,
                st.session_state.tool_name
            )
        
        st.markdown("### 💡 Comprehensive Answer:")
        st.markdown(f"""
        <div style="background-color: #e3f2fd; padding: 25px; border-radius: 10px; 
                    border-left: 5px solid #2196f3; margin: 15px 0;">
            <pre style="white-space: pre-wrap; font-family: inherit; margin: 0;">{answer}</pre>
        </div>
        """, unsafe_allow_html=True)
        
        if debug and sources:
            st.markdown("### 📚 Source Documents:")
            for i, doc in enumerate(sources[:5], 1):
                with st.expander(f"Source {i} - {doc.metadata.get('type', 'unknown')}"):
                    st.text(doc.page_content[:600])
        
        col1, col2 = st.columns([1, 5])
        with col1:
            if st.button("Clear"):
                st.session_state.query = None
                st.rerun()

else:
    st.info("👆 Configure versions and click 'Start Comprehensive Analysis'")

st.markdown("---")
st.caption("🔄 Hybrid RAG: Vector Search + Knowledge Graph | Powered by Phi3 Mini + ChromaDB + Neo4j")