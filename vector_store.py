import faiss
from sentence_transformers import SentenceTransformer
from groq import Groq
import os,json
from database import user_collection, invoice_collection, company_collection,chat_sessions_collection,chat_messages_collection,company_user_collection
# ── FAISS Setup ──────────────────────────────────────────────────────────────
embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
FAISS_DIM = 384
faiss_index = faiss.IndexFlatL2(FAISS_DIM)
faiss_metadata = []  # stores invoice _id mapped to index position


client = Groq(
    api_key=os.getenv("GROQ_API_KEY")
)
def build_faiss_index():
    """Build FAISS index from all existing invoices on startup."""
    global faiss_index, faiss_metadata
    faiss_index = faiss.IndexFlatL2(FAISS_DIM)
    faiss_metadata.clear()
    invoices = list(invoice_collection.find())
    if not invoices:
        print("[FAISS] No invoices found to index.")
        return
    texts = []
    for inv in invoices:
        text = f"{inv.get('vendor_name','')} {inv.get('company','')} {inv.get('invoice_number','')} {inv.get('invoice_date','')} {inv.get('amount','')} {inv.get('gstin','')} {inv.get('status','')} {inv.get('address','')}"
        texts.append(text)
        faiss_metadata.append(str(inv["_id"]))
    embeddings = embedding_model.encode(texts, convert_to_numpy=True)
    faiss_index.add(embeddings)
    # Save to file
    faiss.write_index(faiss_index, "faiss_index.bin")
    with open("faiss_meta.json", "w") as f:
        json.dump(faiss_metadata, f)
    print(f"[FAISS]  Index built and saved with {faiss_index.ntotal} invoices")
    print(f"[FAISS]  Saved to faiss_index.bin and faiss_meta.json")

# Build index on startup
build_faiss_index()
