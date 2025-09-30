import sys, os, json, re, datetime
import torch
import torch.nn as nn
import torch.optim as optim
from collections import Counter

# Text Cleaning
def clean_text(text):
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    text = text.lower()
    text = re.sub(r'[^a-z\s]', ' ', text)
    words = text.split()
    words = [w for w in words if len(w) > 1]
    return words

# JSON Loader 
def load_papers(path):
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if "papers" in data and isinstance(data["papers"], list):
            return data["papers"]
        if "items" in data and isinstance(data["items"], list):
            return data["items"]
    return [data]


ID_KEYS = ["id", "arxiv_id", "paper_id", "uid", "doi"]
ABS_KEYS = ["abstract", "summary", "abstract_text", "description"]

def get_paper_id(paper, default):
    for k in ID_KEYS:
        if k in paper and paper[k]:
            return str(paper[k])
    if "id" in paper and isinstance(paper["id"], dict):
        for v in paper["id"].values():
            if v:
                return str(v)
    return str(default)

def get_paper_abstract(paper):
    for k in ABS_KEYS:
        if k in paper and paper[k]:
            return str(paper[k])
    text_fields = []
    for key in ("title", "authors", "categories", "comment"):
        if key in paper and paper[key]:
            text_fields.append(str(paper[key]))
    return " ".join(text_fields)

# Vocab
def build_vocab(token_lists, max_vocab=5000):
    counter = Counter()
    for toks in token_lists:
        counter.update(toks)
    most_common = counter.most_common(max_vocab)
    vocab = {w: i+1 for i,(w,_) in enumerate(most_common)}
    vocab["<UNK>"] = 0
    return vocab, counter

def encode_text(words, vocab):
    return [vocab.get(w,0) for w in words]

def to_bow(indices, vocab_size):
    vec = torch.zeros(vocab_size, dtype=torch.float32)
    for idx in indices:
        if 0 <= idx < vocab_size:
            vec[idx] = 1.0
    return vec

# Autoencoder
class TextAutoencoder(nn.Module):
    def __init__(self, vocab_size, hidden_dim, embedding_dim):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(vocab_size, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, embedding_dim)
        )
        self.decoder = nn.Sequential(
            nn.Linear(embedding_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, vocab_size),
            nn.Sigmoid()
        )
    def forward(self, x):
        emb = self.encoder(x)
        recon = self.decoder(emb)
        return recon, emb

def count_parameters(model):
    return sum(p.numel() for p in model.parameters())

# Main
def main():
    if len(sys.argv) < 3:
        print("Usage: python train_embeddings.py <input.json> <output_dir> [epochs] [batch_size]")
        sys.exit(1)

    input_file, output_dir = sys.argv[1], sys.argv[2]
    epochs = int(sys.argv[3]) if len(sys.argv) > 3 else 50
    batch_size = int(sys.argv[4]) if len(sys.argv) > 4 else 32
    os.makedirs(output_dir, exist_ok=True)

    # Load data
    raw_papers = load_papers(input_file)

    token_lists, ids = [], []
    for i, p in enumerate(raw_papers):
        toks = clean_text(get_paper_abstract(p))
        if not toks:
            continue
        token_lists.append(toks)
        ids.append(get_paper_id(p, default=i))

    if not token_lists:
        print("Error: no valid abstracts")
        sys.exit(1)

    vocab, counter = build_vocab(token_lists, 5000)
    vocab_size = len(vocab)
    print("Vocabulary size:", vocab_size)

    bows = [to_bow(encode_text(t, vocab), vocab_size) for t in token_lists]
    bow_data = torch.stack(bows)

    hidden_dim, embedding_dim = 256, 64
    model = TextAutoencoder(vocab_size, hidden_dim, embedding_dim)
    total_params = count_parameters(model)
    print("Total parameters:", total_params)
    if total_params > 2_000_000:
        print("Error: too many parameters")
        sys.exit(1)

    criterion = nn.BCELoss()
    optimz = optim.Adam(model.parameters(), lr=1e-3)

    start = datetime.datetime.utcnow().isoformat() + "Z"
    N = bow_data.size(0)
    for ep in range(1, epochs+1):
        perm = torch.randperm(N)
        losses = []
        for i in range(0, N, batch_size):
            b = bow_data[perm[i:i+batch_size]]
            recon, _ = model(b)
            loss = criterion(recon, b)
            optimz.zero_grad()
            loss.backward()
            optimz.step()
            losses.append(loss.item())
        if ep % 10 == 0 or ep == 1 or ep == epochs:
            print(f"Epoch {ep}/{epochs}, Loss: {sum(losses)/len(losses):.4f}")
    end = datetime.datetime.utcnow().isoformat() + "Z"

    # Save outputs
    torch.save({
        "model_state_dict": model.state_dict(),
        "vocab_to_idx": vocab,
        "model_config": {
            "vocab_size": vocab_size,
            "hidden_dim": hidden_dim,
            "embedding_dim": embedding_dim
        }
    }, os.path.join(output_dir, "model.pth"))

    # embeddings.json
    model.eval()
    out_emb = []
    with torch.no_grad():
        per_loss = nn.BCELoss(reduction="mean")
        for pid, bow in zip(ids, bow_data):
            x = bow.unsqueeze(0)
            recon, emb = model(x)
            out_emb.append({
                "arxiv_id": pid,
                "embedding": emb.squeeze(0).tolist(),
                "reconstruction_loss": per_loss(recon, x).item()
            })
    json.dump(out_emb, open(os.path.join(output_dir,"embeddings.json"),"w"))

    # vocab.json
    json.dump({
        "vocab_to_idx": vocab,
        "vocab_size": vocab_size,
        "total_words": int(sum(counter.values()))
    }, open(os.path.join(output_dir,"vocabulary.json"),"w"))

    # log.json
    json.dump({
        "start_time": start,
        "end_time": end,
        "epochs": epochs,
        "final_loss": loss.item(),
        "total_parameters": int(total_params),
        "papers_processed": N,
        "embedding_dimension": embedding_dim
    }, open(os.path.join(output_dir,"training_log.json"),"w"))

if __name__ == "__main__":
    main()
