from sentence_transformers import SentenceTransformer, util
import torch

class SemanticTranslator:
    def __init__(self, standard_schema):
        # Load a lightweight, efficient model (approx 80MB)
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        self.standard_schema = standard_schema
        # Cache the mathematical vectors for your schema
        self.schema_embeddings = self.model.encode(standard_schema, convert_to_tensor=True)

    def resolve(self, messy_field, threshold=0.75):
        # Convert messy input to a vector
        input_embedding = self.model.encode(messy_field, convert_to_tensor=True)
        
        # Calculate similarity against your standard schema
        scores = util.cos_sim(input_embedding, self.schema_embeddings)[0]
        
        # Find the highest match
        best_match_idx = torch.argmax(scores).item()
        confidence = scores[best_match_idx].item()
        
        if confidence >= threshold:
            return self.standard_schema[best_match_idx], confidence
        return None, confidence