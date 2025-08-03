import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings

# --- Step 1: ENV setup ---
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# --- Step 2: Crawler ---
BASE_URL_WIKI = "https://wiki.freecad.org/Power_users_hub"
BASE_URL_GITHUB = "https://github.com/shaise/FreeCAD_FastenersWB"

DOMAIN_WHITELIST = [
    "https://wiki.freecad.org",
    "https://github.com/shaise"
]

# List of language identifiers to exclude (only for wiki)
LANG_IDENTIFIERS = [
    "/id", "/de", "/tr", "/es", "/fr", "/hr", "/it", "/pl",
    "/pt", "/pt-br", "/ro", "/fi", "/sv", "/cs", "/ru", "/zh-cn",
    "/zh-tw", "/ja", "/ko"
]

def is_excluded_url(url):
    url_lower = url.lower()

    # Apply language filters only to FreeCAD wiki URLs
    if "wiki.freecad.org" in url_lower:
        if any(lang in url_lower for lang in LANG_IDENTIFIERS):
            return True

    return (
        ".jpg" in url_lower or
        ".png" in url_lower or
        "edit&section" in url_lower
    )

def crawl_wiki(start_url, max_pages):
    visited = set()
    to_visit = [start_url]
    pages = []

    while to_visit and len(visited) < max_pages:
        url = to_visit.pop(0)
        if url in visited or is_excluded_url(url):
            continue
        try:
            print(f"Fetching: {url}")
            res = requests.get(url)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, "html.parser")
            visited.add(url)

            for tag in soup(["script", "style", "header", "footer", "nav", "aside"]):
                tag.extract()
            text = soup.get_text(separator="\n")
            clean = "\n".join([line.strip() for line in text.splitlines() if line.strip()])
            pages.append({"url": url, "text": clean})

            # Queue internal links
            for a in soup.find_all("a", href=True):
                full = urljoin(url, a["href"])
                if any(full.startswith(domain) for domain in DOMAIN_WHITELIST):
                    if full not in visited and not is_excluded_url(full):
                        to_visit.append(full)
        except Exception as e:
            print(f"Error fetching {url}: {e}")

    print(f"Crawled {len(pages)} pages from {start_url}")
    return pages

# --- Step 3: RAG Build ---
def build_vectorstore():
    wiki_pages = crawl_wiki(BASE_URL_WIKI, max_pages=2000)  # Uncomment if you want both
    github_pages = crawl_wiki(BASE_URL_GITHUB, max_pages=450)
    pages = wiki_pages + github_pages

    if not pages:
        print("No pages crawled. Exiting.")
        return

    texts = [p["text"] for p in pages]
    metadatas = [{"source": p["url"]} for p in pages]

    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    docs = splitter.create_documents(texts, metadatas=metadatas)

    print(f"Split into {len(docs)} chunks")

    embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
    vectorstore = FAISS.from_documents(docs, embeddings)

    src_path = os.path.dirname(os.path.abspath(__file__))
    root_dir_path = os.path.dirname(src_path)
    vectorstore_path = os.path.join(root_dir_path, "vectorstore")

    os.makedirs(vectorstore_path, exist_ok=True)
    vectorstore.save_local(vectorstore_path)
    print("Vectorstore saved to ./vectorstore")

if __name__ == "__main__":
    build_vectorstore()
