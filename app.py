"""
DevOps Upgrade Intelligence Assistant - PRODUCTION FINAL
- Works with ANY Kubernetes changelog URL
- Proper ChromaDB initialization (no tenant error)
- Clear difference between Vector-Only and Hybrid RAG
- Comprehensive upgrade path analysis
"""

import streamlit as st
import requests
import re
import os
import shutil
from typing import List, Dict, Tuple
from dataclasses import dataclass

from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.chat_models import ChatOllama
from langchain.prompts import PromptTemplate
from langchain.docstore.document import Document
from langchain.chains import LLMChain
from neo4j import GraphDatabase
import chromadb

# Page config
st.set_page_config(page_title="DevOps Upgrade Assistant", layout="wide", page_icon="🔄")

st.title("🔄 DevOps Upgrade Intelligence Assistant")
st.markdown("*Analyze Kubernetes upgrades with Vector Search + Knowledge Graph*")

# Session state
if 'ready' not in st.session_state:
    st.session_state.ready = False
if 'vectordb' not in st.session_state:
    st.session_state.vectordb = None
if 'kg' not in st.session_state:
    st.session_state.kg = None
if 'neo4j_enabled' not in st.session_state:
    st.session_state.neo4j_enabled = False

# Sidebar
with st.sidebar:
    st.header("⚙️ Configuration")
    
    st.markdown("### 🗄️ Neo4j Knowledge Graph")
    st.info("Enable for upgrade path analysis and version relationships")
    
    use_neo4j = st.checkbox("Enable Neo4j KG", value=False)
    
    if use_neo4j:
        neo4j_uri = st.text_input("URI", "bolt://localhost:7687")
        neo4j_user = st.text_input("User", "neo4j")
        neo4j_pass = st.text_input("Password", "password", type="password")
        
        if st.button("Test Connection"):
            try:
                driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_pass))
                with driver.session() as session:
                    result = session.run("RETURN 1")
                    result.single()
                driver.close()
                st.success("✅ Neo4j Connected!")
            except Exception as e:
                st.error(f"❌ Failed: {str(e)}")
    
    st.markdown("---")
    if st.button("🗑️ Reset All"):
        if os.path.exists("./chroma_db"):
            shutil.rmtree("./chroma_db")
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

# Data models
@dataclass
class VersionData:
    version: str
    content: str
    breaking_changes: List[str]
    deprecations: List[str]
    removals: List[str]
    security_fixes: List[str]

# Helper functions
def fetch_from_url(url: str) -> str:
    """Fetch changelog from any GitHub URL"""
    try:
        # Convert GitHub blob URLs to raw
        if 'github.com' in url and '/blob/' in url:
            url = url.replace('github.com', 'raw.githubusercontent.com').replace('/blob/', '/')
        
        st.write(f"📥 Fetching: {url}")
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        return response.text
    except Exception as e:
        st.error(f"❌ Fetch failed: {str(e)}")
        return None

def parse_changelog_flexible(content: str) -> List[VersionData]:
    """Parse ANY Kubernetes changelog format"""
    if not content:
        return []
    
    versions = []
    lines = content.split('\n')
    current_version = None
    current_content = []
    current_breaking = []
    current_deprecated = []
    current_removed = []
    current_security = []
    
    for line in lines:
        # Match version headers: # v1.24.0, ## v1.24.0, ### 1.24.0, etc.
        version_match = re.match(r'^#{1,4}\s*v?(\d+\.\d+\.\d+)', line, re.IGNORECASE)
        
        if version_match:
            # Save previous version
            if current_version and len(current_content) > 5:
                versions.append(VersionData(
                    version=current_version,
                    content='\n'.join(current_content),
                    breaking_changes=current_breaking[:],
                    deprecations=current_deprecated[:],
                    removals=current_removed[:],
                    security_fixes=current_security[:]
                ))
            
            # Start new version
            current_version = version_match.group(1)
            current_content = [line]
            current_breaking = []
            current_deprecated = []
            current_removed = []
            current_security = []
        else:
            if current_version:
                current_content.append(line)
                line_lower = line.lower()
                
                # Flexible pattern matching
                # Breaking changes
                if any(pattern in line_lower for pattern in [
                    'breaking', 'breaks', 'incompatible', 'removed api', 'removed feature'
                ]):
                    if line.strip() and not line.strip().startswith('#'):
                        current_breaking.append(line.strip())
                
                # Deprecations
                if any(pattern in line_lower for pattern in [
                    'deprecat', 'will be removed', 'obsolete', 'legacy'
                ]):
                    if line.strip() and not line.strip().startswith('#'):
                        current_deprecated.append(line.strip())
                
                # Removals
                if any(pattern in line_lower for pattern in [
                    'removed', 'deleted', 'dropped'
                ]) and 'deprecat' not in line_lower:
                    if line.strip() and not line.strip().startswith('#'):
                        current_removed.append(line.strip())
                
                # Security
                if any(pattern in line_lower for pattern in [
                    'cve-', 'security', 'vulnerability', 'exploit', 'patch'
                ]):
                    if line.strip() and not line.strip().startswith('#'):
                        current_security.append(line.strip())
    
    # Save last version
    if current_version and len(current_content) > 5:
        versions.append(VersionData(
            version=current_version,
            content='\n'.join(current_content),
            breaking_changes=current_breaking,
            deprecations=current_deprecated,
            removals=current_removed,
            security_fixes=current_security
        ))
    
    return versions

# Neo4j Knowledge Graph
class KnowledgeGraph:
    def __init__(self, uri, user, password):
        self.connected = False
        self.driver = None
        try:
            self.driver = GraphDatabase.driver(uri, auth=(user, password))
            with self.driver.session() as session:
                result = session.run("RETURN 1")
                result.single()
            self.connected = True
            st.sidebar.success("✅ Neo4j Connected")
        except Exception as e:
            st.sidebar.error(f"❌ Neo4j: {str(e)[:50]}")
    
    def create_graph(self, versions: List[VersionData]):
        if not self.connected:
            return
        
        with self.driver.session() as session:
            # Clear old data
            session.run("MATCH (n) DETACH DELETE n")
            
            # Create version nodes
            for v in versions:
                session.run("""
                    CREATE (v:Version {
                        name: $version,
                        has_breaking: $breaking,
                        has_deprecated: $deprecated,
                        has_removed: $removed,
                        has_security: $security,
                        num_breaking: $num_breaking,
                        num_deprecated: $num_deprecated
                    })
                    """,
                    version=v.version,
                    breaking=len(v.breaking_changes) > 0,
                    deprecated=len(v.deprecations) > 0,
                    removed=len(v.removals) > 0,
                    security=len(v.security_fixes) > 0,
                    num_breaking=len(v.breaking_changes),
                    num_deprecated=len(v.deprecations)
                )
            
            # Create PRECEDES relationships
            sorted_v = sorted(versions, key=lambda x: tuple(map(int, x.version.split('.'))))
            for i in range(len(sorted_v) - 1):
                session.run("""
                    MATCH (v1:Version {name: $v1})
                    MATCH (v2:Version {name: $v2})
                    CREATE (v1)-[:PRECEDES]->(v2)
                    """,
                    v1=sorted_v[i].version,
                    v2=sorted_v[i+1].version
                )
        
        st.success(f"✅ Neo4j: {len(versions)} versions mapped")
    
    def analyze_path(self, start: str, end: str) -> str:
        """Get upgrade path analysis"""
        if not self.connected:
            return ""
        
        with self.driver.session() as session:
            result = session.run("""
                MATCH path = (v1:Version {name: $start})-[:PRECEDES*]->(v2:Version {name: $end})
                WITH nodes(path) as versions
                UNWIND versions as v
                RETURN 
                    v.name as version,
                    v.has_breaking as has_breaking,
                    v.has_deprecated as has_deprecated,
                    v.has_security as has_security,
                    v.num_breaking as num_breaking,
                    v.num_deprecated as num_deprecated
                ORDER BY v.name
                """, start=start, end=end)
            
            analysis = f"\n📊 KNOWLEDGE GRAPH ANALYSIS:\n"
            analysis += f"Upgrade Path: {start} → {end}\n\n"
            
            critical_count = 0
            for record in result:
                v = record['version']
                flags = []
                
                if record['has_breaking']:
                    flags.append(f"⚠️ BREAKING ({record['num_breaking']})")
                    critical_count += 1
                if record['has_deprecated']:
                    flags.append(f"DEPRECATED ({record['num_deprecated']})")
                if record['has_security']:
                    flags.append("SECURITY")
                
                status = " | ".join(flags) if flags else "✅ Safe"
                analysis += f"v{v}: {status}\n"
            
            analysis += f"\n🎯 Critical versions: {critical_count}\n"
            return analysis
    
    def close(self):
        if self.driver:
            self.driver.close()

# Initialize models
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
        return llm
    except:
        st.error("❌ Ollama not running. Start: `ollama serve`")
        st.stop()

embeddings = get_embeddings()
llm = get_llm()

# DIFFERENT PROMPTS
VECTOR_ONLY_PROMPT = PromptTemplate(
    template="""You are a DevOps expert analyzing Kubernetes changelogs.

CHANGELOG EXCERPTS:
{context}

QUESTION: {question}

INSTRUCTIONS:
- Answer ONLY from the provided changelog excerpts
- Be concise - use bullet points
- Include version numbers
- If information not found, say "Not found in provided changelog"

Answer:""",
    input_variables=["context", "question"]
)

HYBRID_PROMPT = PromptTemplate(
    template="""You are a senior DevOps engineer with access to both detailed changelog content AND version relationship data.

DETAILED CHANGELOG CONTENT:
{context}

UPGRADE PATH ANALYSIS FROM KNOWLEDGE GRAPH:
{kg_analysis}

QUESTION: {question}

INSTRUCTIONS:
- Use BOTH the changelog content AND the knowledge graph analysis
- The knowledge graph shows version sequences, critical path, and relationships
- Provide comprehensive upgrade path recommendations
- Highlight critical versions (those with breaking changes)
- Include timeline and sequence information from the graph
- Give specific, actionable migration steps
- Assess risks of skipping versions

RESPONSE FORMAT:
1. Summary of findings
2. Critical path analysis (use graph data)
3. Specific changes by version
4. Recommended upgrade sequence
5. Risk assessment

Answer:""",
    input_variables=["context", "kg_analysis", "question"]
)

# Main analysis
def analyze_changelogs(url1: str, url2: str, enable_kg: bool):
    """Analyze changelogs"""
    
    st.markdown("---")
    st.subheader("📊 Analysis")
    
    # Fetch
    with st.spinner("📥 Fetching changelogs..."):
        content1 = fetch_from_url(url1)
        content2 = fetch_from_url(url2)
        
        if not content1 or not content2:
            return None, None, None
    
    # Parse
    with st.spinner("📝 Parsing versions..."):
        versions1 = parse_changelog_flexible(content1)
        versions2 = parse_changelog_flexible(content2)
        
        # Merge and deduplicate
        all_versions = {}
        for v in versions1 + versions2:
            if v.version not in all_versions:
                all_versions[v.version] = v
        
        versions = list(all_versions.values())
        versions.sort(key=lambda x: tuple(map(int, x.version.split('.'))))
    
    st.success(f"✅ Parsed {len(versions)} versions")
    
    # Statistics
    total_breaking = sum(len(v.breaking_changes) for v in versions)
    total_deprecated = sum(len(v.deprecations) for v in versions)
    total_removed = sum(len(v.removals) for v in versions)
    total_security = sum(len(v.security_fixes) for v in versions)
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🔴 Breaking", total_breaking)
    col2.metric("⚠️ Deprecated", total_deprecated)
    col3.metric("❌ Removed", total_removed)
    col4.metric("🔒 Security", total_security)
    
    # Build Knowledge Graph
    kg = None
    if enable_kg:
        with st.spinner("🕸️ Building Knowledge Graph..."):
            kg = KnowledgeGraph(neo4j_uri, neo4j_user, neo4j_pass)
            if kg.connected:
                kg.create_graph(versions)
    
    # Build Vector DB - FIXED ChromaDB initialization
    with st.spinner("🗄️ Building Vector Database..."):
        try:
            # Prepare documents
            docs = []
            for v in versions:
                # Full content
                docs.append(Document(
                    page_content=f"Version {v.version}\n\n{v.content}",
                    metadata={"version": v.version, "type": "full"}
                ))
                
                # Individual changes
                for item in v.breaking_changes[:10]:  # Limit to prevent bloat
                    docs.append(Document(
                        page_content=f"[BREAKING] v{v.version}: {item}",
                        metadata={"version": v.version, "type": "breaking"}
                    ))
                
                for item in v.deprecations[:10]:
                    docs.append(Document(
                        page_content=f"[DEPRECATED] v{v.version}: {item}",
                        metadata={"version": v.version, "type": "deprecated"}
                    ))
            
            # Clear old DB
            db_path = "./chroma_db"
            if os.path.exists(db_path):
                shutil.rmtree(db_path)
            os.makedirs(db_path, exist_ok=True)
            
            # FIXED: Use PersistentClient to avoid tenant error
            chroma_client = chromadb.PersistentClient(path=db_path)
            
            # Create collection
            try:
                chroma_client.delete_collection("changelogs")
            except:
                pass
            
            # Create vector store
            vectordb = Chroma.from_documents(
                documents=docs,
                embedding=embeddings,
                client=chroma_client,
                collection_name="changelogs"
            )
            
            st.success(f"✅ Vector DB: {len(docs)} documents")
            
            return vectordb, kg, versions
            
        except Exception as e:
            st.error(f"❌ Vector DB error: {str(e)}")
            import traceback
            st.code(traceback.format_exc())
            return None, kg, versions

# Query function
def query_system(question: str, vectordb, kg, versions, start_v: str, end_v: str):
    """Query with vector-only or hybrid mode"""
    
    if not vectordb:
        return "❌ Vector DB not ready", "N/A"
    
    # Vector search
    retriever = vectordb.as_retriever(search_kwargs={"k": 8})
    docs = retriever.get_relevant_documents(question)
    context = "\n\n".join([d.page_content for d in docs])
    
    # Check mode
    if kg and kg.connected:
        # HYBRID MODE
        st.info("🔄 **Hybrid RAG Mode**: Vector Search + Knowledge Graph")
        
        # Get KG analysis
        kg_analysis = kg.analyze_path(start_v, end_v)
        
        # Use hybrid prompt
        chain = LLMChain(llm=llm, prompt=HYBRID_PROMPT)
        answer = chain.run(
            context=context,
            kg_analysis=kg_analysis,
            question=question
        )
        
        mode = "Hybrid RAG (Vector + Knowledge Graph)"
    else:
        # VECTOR-ONLY MODE
        st.warning("⚠️ **Vector-Only Mode**: Basic search (Enable Neo4j for path analysis)")
        
        # Use vector-only prompt
        chain = LLMChain(llm=llm, prompt=VECTOR_ONLY_PROMPT)
        answer = chain.run(
            context=context,
            question=question
        )
        
        mode = "Vector-Only"
    
    return answer, mode

# UI - Input
st.markdown("### 📎 Paste Kubernetes Changelog URLs")

st.info("💡 Works with any Kubernetes changelog format (1.20, 1.24, 1.28, etc.)")

col1, col2 = st.columns(2)
with col1:
    url1 = st.text_input(
        "Current Version",
        placeholder="https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG/CHANGELOG-1.20.md",
        help="Any Kubernetes changelog URL"
    )
with col2:
    url2 = st.text_input(
        "Target Version",
        placeholder="https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG/CHANGELOG-1.24.md",
        help="Any Kubernetes changelog URL"
    )

if st.button("🚀 Analyze Changelogs", type="primary", disabled=not url1 or not url2):
    # Extract versions from URLs
    v1_match = re.search(r'(\d+\.\d+\.\d+)', url1)
    v2_match = re.search(r'(\d+\.\d+\.\d+)', url2)
    
    if not v1_match:
        v1_match = re.search(r'CHANGELOG-(\d+\.\d+)', url1)
        v1 = v1_match.group(1) + ".0" if v1_match else "unknown"
    else:
        v1 = v1_match.group(1)
    
    if not v2_match:
        v2_match = re.search(r'CHANGELOG-(\d+\.\d+)', url2)
        v2 = v2_match.group(1) + ".0" if v2_match else "unknown"
    else:
        v2 = v2_match.group(1)
    
    vectordb, kg, versions = analyze_changelogs(url1, url2, use_neo4j)
    
    if vectordb and versions:
        st.session_state.vectordb = vectordb
        st.session_state.kg = kg
        st.session_state.versions = versions
        st.session_state.ready = True
        st.session_state.start_v = v1
        st.session_state.end_v = v2
        st.session_state.neo4j_enabled = (kg.connected if kg else False)
        st.balloons()

# UI - Questions
if st.session_state.ready:
    st.markdown("---")
    st.subheader("💬 Ask Questions")
    
    # Show mode
    if st.session_state.neo4j_enabled:
        st.success("✅ **Hybrid RAG**: Using Vector DB + Knowledge Graph")
    else:
        st.info("ℹ️ **Vector-Only**: Enable Neo4j for upgrade path analysis")
    
    # Preset questions
    questions = {
        "Breaking Changes": "What are ALL the breaking changes?",
        "Deprecations": "What is deprecated and when will it be removed?",
        "Safe to Skip?": "Is it safe to skip directly? What are the risks?",
        "Upgrade Path": "What is the recommended upgrade path?",
        "Critical Issues": "What are the most critical issues?"
    }
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**Quick Questions**")
        selected = st.selectbox("Select:", list(questions.keys()))
        if st.button("Ask"):
            st.session_state.query = questions[selected]
    
    with col2:
        st.markdown("**Custom**")
        custom = st.text_area("Question:", height=80)
        if st.button("Submit"):
            if custom:
                st.session_state.query = custom
    
    # Display answer
    if 'query' in st.session_state and st.session_state.query:
        st.markdown("---")
        st.markdown(f"**Q:** {st.session_state.query}")
        
        with st.spinner("Analyzing..."):
            answer, mode = query_system(
                st.session_state.query,
                st.session_state.vectordb,
                st.session_state.kg,
                st.session_state.versions,
                st.session_state.start_v,
                st.session_state.end_v
            )
        
        st.caption(f"Mode: {mode}")
        
        st.markdown("**Answer:**")
        st.markdown(f"""
<div style="background-color: #f0f9ff; padding: 20px; border-radius: 8px; border-left: 4px solid #0284c7;">
<pre style="white-space: pre-wrap; font-family: 'Segoe UI', sans-serif; margin: 0; line-height: 1.6;">{answer}</pre>
</div>
        """, unsafe_allow_html=True)
        
        if st.button("Clear"):
            del st.session_state.query
            st.rerun()

else:
    st.info("👆 Paste changelog URLs and click 'Analyze'")

st.markdown("---")
st.caption("Powered by Phi3 Mini + ChromaDB + Neo4j")