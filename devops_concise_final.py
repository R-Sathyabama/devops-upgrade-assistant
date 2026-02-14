"""
DevOps Upgrade Assistant - Final Production Version
- Accurate extraction of critical changes
- Concise, bullet-point answers
- Human-readable format
- Works with/without Neo4j
"""

import streamlit as st
import requests
import re
import os
import shutil
from typing import List, Dict, Tuple
from dataclasses import dataclass
from enum import Enum

from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.chat_models import ChatOllama
from langchain.prompts import PromptTemplate
from langchain.docstore.document import Document
from langchain.chains import LLMChain
from chromadb.config import Settings

# Page config
st.set_page_config(page_title="DevOps Upgrade Assistant", layout="wide", page_icon="🔄")
st.title("🔄 DevOps Upgrade Assistant")
st.markdown("*Concise, accurate upgrade analysis*")

# Session state
for key in ['vectordb', 'current_version', 'target_version', 'tool_name', 'ready', 'all_changes']:
    if key not in st.session_state:
        st.session_state[key] = None if key != 'all_changes' else []

# Sidebar
with st.sidebar:
    st.header("⚙️ Config")
    tool = st.selectbox("Tool", ["Kubernetes", "Terraform", "Docker"])
    current = st.text_input("Current", "1.20.0")
    target = st.text_input("Target", "1.24.0")
    st.markdown("---")
    debug = st.checkbox("Debug")
    
    if st.button("Reset"):
        if os.path.exists("./chroma_db"):
            shutil.rmtree("./chroma_db")
        st.rerun()

# Helpers
def norm_version(v: str) -> str:
    return v[1:] if v.startswith('v') else v.strip()

def fetch_k8s_changelog(v: str) -> Tuple[str, str]:
    parts = v.split('.')
    if len(parts) >= 2:
        url = f"https://raw.githubusercontent.com/kubernetes/kubernetes/master/CHANGELOG/CHANGELOG-{parts[0]}.{parts[1]}.md"
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                return r.text, url
        except:
            pass
    return None, None

def parse_k8s_changelog(content: str) -> List[Dict]:
    """Parse changelog and extract version sections"""
    if not content:
        return []
    
    versions = []
    lines = content.split('\n')
    curr_ver = None
    curr_content = []
    
    for line in lines:
        match = re.match(r'^#{1,2}\s+v?(\d+\.\d+\.\d+)', line)
        if match:
            if curr_ver and curr_content:
                text = '\n'.join(curr_content)
                if len(text.strip()) > 50:
                    versions.append({'version': curr_ver, 'content': text})
            curr_ver = match.group(1)
            curr_content = [line]
        else:
            if curr_ver:
                curr_content.append(line)
    
    if curr_ver and curr_content:
        text = '\n'.join(curr_content)
        if len(text.strip()) > 50:
            versions.append({'version': curr_ver, 'content': text})
    
    return versions

def filter_versions(versions: List[Dict], start: str, end: str) -> List[Dict]:
    def ver_tuple(v):
        try:
            return tuple(map(int, v.split('.')))
        except:
            return (0, 0, 0)
    
    start_t, end_t = ver_tuple(start), ver_tuple(end)
    return [v for v in versions if start_t <= ver_tuple(v['version']) <= end_t]

# Initialize
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
llm, ok = get_llm()

if not ok:
    st.error("❌ Ollama not running")
    st.stop()

# Concise prompt - KEY IMPROVEMENT
CONCISE_PROMPT = PromptTemplate(
    template="""You are a DevOps expert. Analyze the changelog and provide a CONCISE answer.

CHANGELOG:
{context}

VERSION: {current_version} → {target_version}
QUESTION: {question}

FORMAT YOUR ANSWER AS:
• Use bullet points (•)
• One line per item
• Format: "• Version X.Y.Z: Brief description (Component: name)"
• NO long paragraphs
• NO URLs or PR numbers
• NO unnecessary explanations
• Just facts: version, what changed, what to do

Example good answer:
• Version 1.22.0: CronJob batch/v1beta1 API removed (Component: batch API)
  → Action: Update manifests to batch/v1
• Version 1.24.0: Dockershim removed (Component: Container Runtime)
  → Action: Switch to containerd or CRI-O

ANSWER:""",
    input_variables=["context", "current_version", "target_version", "question"]
)

# Analysis
def analyze(tool: str, curr: str, targ: str):
    st.markdown("---")
    st.subheader(f"📊 {tool}")
    
    curr, targ = norm_version(curr), norm_version(targ)
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("From", curr)
    with col2:
        st.metric("To", targ)
    
    with st.spinner("Fetching..."):
        all_vers = []
        if tool == "Kubernetes":
            c1, _ = fetch_k8s_changelog(curr)
            if c1:
                st.success(f"✅ {curr}")
                all_vers.extend(parse_k8s_changelog(c1))
            
            c2, _ = fetch_k8s_changelog(targ)
            if c2 and c2 != c1:
                st.success(f"✅ {targ}")
                all_vers.extend(parse_k8s_changelog(c2))
    
    if not all_vers:
        st.error("❌ No data")
        return None
    
    # Dedupe
    seen = set()
    unique = []
    for v in all_vers:
        if v['version'] not in seen:
            seen.add(v['version'])
            unique.append(v)
    
    # Filter
    filtered = filter_versions(unique, curr, targ)
    if not filtered:
        filtered = unique[:15]
    
    st.info(f"📝 {len(filtered)} versions")
    
    # Build vector DB
    with st.spinner("Building DB..."):
        try:
            combined = "\n\n".join([f"# Version {v['version']}\n{v['content']}" for v in filtered])
            
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=1500,
                chunk_overlap=300,
                separators=["\n## ", "\n### ", "\n\n", "\n"]
            )
            chunks = splitter.split_text(combined)
            
            docs = [Document(page_content=c, metadata={"chunk": i}) for i, c in enumerate(chunks)]
            
            db_path = "./chroma_db"
            if os.path.exists(db_path):
                shutil.rmtree(db_path)
            os.makedirs(db_path, exist_ok=True)
            
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
                collection_name="docs"
            )
            
            vectordb.persist()
            st.success(f"✅ {len(docs)} chunks")
            
            return vectordb, filtered
        except Exception as e:
            st.error(f"Error: {e}")
            return None, filtered

# Query
def query(q: str, vectordb, curr: str, targ: str):
    if not vectordb:
        return "❌ No database", []
    
    try:
        retriever = vectordb.as_retriever(search_kwargs={"k": 8})
        docs = retriever.get_relevant_documents(q)
        context = "\n\n".join([d.page_content for d in docs])
        
        chain = LLMChain(llm=llm, prompt=CONCISE_PROMPT)
        result = chain.run(
            context=context,
            current_version=curr,
            target_version=targ,
            question=q
        )
        
        return result, docs
    except Exception as e:
        return f"Error: {e}", []

# UI
st.info("💡 Enter versions → Analyze → Ask questions → Get concise answers")

if st.button("🚀 Analyze", type="primary", disabled=not current or not target):
    st.session_state.current_version = norm_version(current)
    st.session_state.target_version = norm_version(target)
    st.session_state.tool_name = tool
    
    vdb, vers = analyze(tool, current, target)
    
    if vdb:
        st.session_state.vectordb = vdb
        st.session_state.ready = True
        st.success("✅ Ready!")

if st.session_state.ready:
    st.markdown("---")
    st.subheader("💬 Questions")
    
    st.caption(f"{st.session_state.tool_name} | {st.session_state.current_version} → {st.session_state.target_version}")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### Quick")
        questions = {
            "Breaking": "List ALL breaking changes in bullet points",
            "Deprecations": "List ALL deprecations in bullet points",
            "Removals": "List ALL removals in bullet points",
            "Security": "List ALL security fixes in bullet points",
            "Summary": "Provide concise upgrade summary in bullet points"
        }
        sel = st.selectbox("Select:", list(questions.keys()))
        if st.button("Ask"):
            st.session_state.query = questions[sel]
    
    with col2:
        st.markdown("#### Custom")
        custom = st.text_area("Question:", height=80)
        if st.button("Submit"):
            if custom:
                st.session_state.query = custom
    
    if 'query' in st.session_state and st.session_state.query:
        st.markdown("---")
        st.markdown(f"### ❓ {st.session_state.query}")
        
        with st.spinner("Analyzing..."):
            answer, sources = query(
                st.session_state.query,
                st.session_state.vectordb,
                st.session_state.current_version,
                st.session_state.target_version
            )
        
        st.markdown("### 💡 Answer:")
        st.markdown(f"""
<div style="background-color: #f0f9ff; padding: 20px; border-radius: 8px; border-left: 4px solid #0284c7;">
<pre style="white-space: pre-wrap; font-family: 'Segoe UI', sans-serif; margin: 0; line-height: 1.6;">{answer}</pre>
</div>
        """, unsafe_allow_html=True)
        
        if debug and sources:
            st.markdown("### 📚 Sources:")
            for i, d in enumerate(sources[:3], 1):
                with st.expander(f"Source {i}"):
                    st.text(d.page_content[:400])
        
        if st.button("Clear"):
            st.session_state.query = None
            st.rerun()

else:
    st.info("👆 Enter versions and click Analyze")

st.markdown("---")
st.caption("Powered by Phi3 + ChromaDB")